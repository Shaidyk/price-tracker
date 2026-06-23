"""Celery-пайплайн сбора цен.

chord( group(fetch_shop_prices по магазинам) )( recompute_daily_stats → check_price_alerts ):
магазины собираются параллельно, агрегаты считаем один раз — когда все цены за день
собраны. Таски только оркестрируют; запись/расчёт — в services.
"""

from __future__ import annotations

import datetime as dt
import logging

from celery import chord, group, shared_task
from django.utils import timezone

from apps.catalog.models import Offer, Shop
from apps.integrations.shops.base import IntegrationError
from apps.integrations.shops.registry import get_shop_client

from .services import recompute_daily_stats, record_price

logger = logging.getLogger(__name__)


@shared_task
def fetch_all_prices(date_iso: str | None = None) -> str:
    """Запустить сбор цен по всем активным магазинам и пост-обработку."""
    on_date = date_iso or timezone.localdate().isoformat()
    shop_codes = list(Shop.objects.filter(is_active=True).values_list("code", flat=True))
    if not shop_codes:
        logger.warning("Нет активных магазинов — сбор цен пропущен")
        return on_date

    header = group(fetch_shop_prices.s(code, on_date) for code in shop_codes)
    callback = recompute_and_alert.s(on_date)
    chord(header)(callback)
    return on_date


@shared_task(bind=True, max_retries=3)
def fetch_shop_prices(self, shop_code: str, date_iso: str) -> int:
    """Собрать цены одного магазина и записать PriceRecord за день.

    Член chord: при сбое магазина после исчерпания ретраев возвращаем 0, а не
    падаем, — иначе chord не запустит callback и снимок дня потеряется.
    """
    on_date = dt.date.fromisoformat(date_iso)
    try:
        shop = Shop.objects.get(code=shop_code, is_active=True)
    except Shop.DoesNotExist:
        logger.info("Магазин %s неактивен/удалён — пропуск", shop_code)
        return 0

    try:
        client = get_shop_client(shop_code)
    except ValueError:
        # Адаптера для этого code нет в реестре — конфиг-ошибка, ретрай не поможет.
        logger.error("Магазин %s: нет адаптера в реестре — пропуск", shop_code)
        return 0

    try:
        products = client.fetch_products()
    except IntegrationError as exc:
        # На исчерпании ретраев Celery ре-райзит сам exc (не MaxRetriesExceededError,
        # раз передали exc=), поэтому решаем явно, а не ловим его.
        if self.request.retries >= self.max_retries:
            logger.error("Магазин %s недоступен после ретраев — пропуск дня", shop_code)
            return 0  # chord продолжится без этого магазина
        raise self.retry(exc=exc, countdown=2 ** self.request.retries) from exc

    price_by_external = {p.external_id: p.price_usd for p in products}
    offers = Offer.objects.filter(shop=shop, is_active=True).select_related("product")
    saved = 0
    for offer in offers:
        price = price_by_external.get(offer.external_id)
        if price is None or price <= 0:
            continue  # нет в выдаче или нулевая/мусорная цена — не ошибка
        try:
            record_price(offer, price, on_date)
            saved += 1
        except Exception:  # noqa: BLE001 — один битый товар не должен ронять магазин
            logger.exception("Не удалось записать цену offer=%s", offer.id)
    logger.info("Магазин %s: записано цен %d за %s", shop_code, saved, on_date)
    return saved


@shared_task
def recompute_and_alert(_results: list[int], date_iso: str) -> int:
    """Callback chord: пересчитать агрегаты, затем проверить алерты.

    `_results` — список результатов fetch_shop_prices по магазинам (нам не важен).
    """
    on_date = dt.date.fromisoformat(date_iso)
    updated = recompute_daily_stats(on_date)
    logger.info("Пересчитано агрегатов товаров: %d за %s", updated, on_date)
    # импорт здесь, чтобы не создавать циклическую зависимость приложений
    from apps.alerts.tasks import check_price_alerts

    check_price_alerts.delay(date_iso)
    return updated
