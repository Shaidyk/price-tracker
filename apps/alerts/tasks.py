"""Celery-проверка алертов: «цена опустилась ниже указанной» → email.

Запускается из пайплайна цен после пересчёта агрегатов. Идемпотентно по дню:
`last_notified_date` не даёт слать одно письмо повторно при каждом прогоне.
"""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from apps.currency.services import RateUnavailable, conversion_factor, quantize_money
from apps.pricing.models import ProductDailyStat

from .models import PriceAlert

logger = logging.getLogger(__name__)


@shared_task
def check_price_alerts(date_iso: str | None = None) -> int:
    """Проверить активные алерты по ценам на дату; отправить письма. Вернуть число писем.

    Без N+1: цены на день и множители валют подгружаются пачкой ДО цикла —
    один запрос на цены и по одному множителю на уникальную валюту.
    """
    on_date = dt.date.fromisoformat(date_iso) if date_iso else timezone.localdate()

    alerts = list(
        PriceAlert.objects.filter(is_active=True).select_related("user", "product")
    )
    if not alerts:
        return 0

    # цены по всем нужным товарам — одним запросом
    product_ids = {a.product_id for a in alerts}
    prices_usd: dict[int, Decimal] = dict(
        ProductDailyStat.objects.filter(product_id__in=product_ids, date=on_date)
        .values_list("product_id", "min_price_usd")
    )

    # множитель на уникальную валюту — по разу (RateUnavailable → валюта недоступна)
    factors: dict[str, Decimal | None] = {}
    for code in {a.currency for a in alerts}:
        try:
            factors[code] = conversion_factor(code, on_date)
        except RateUnavailable:
            factors[code] = None
            logger.warning("Нет курса %s на %s — алерты в этой валюте пропущены", code, on_date)

    sent = 0
    for alert in alerts:
        if alert.last_notified_date == on_date:
            continue  # уже уведомляли сегодня — не спамим
        price_usd = prices_usd.get(alert.product_id)
        factor = factors.get(alert.currency)
        if price_usd is None or factor is None:
            continue
        current = quantize_money(price_usd * factor)
        # Строгое сравнение: цена, равная порогу, ещё не «ниже». Сравниваем
        # минимальную цену товара среди магазинов.
        if current < alert.target_price and _notify(alert, current, on_date):
            # помечаем уведомлённым ТОЛЬКО если письмо реально ушло
            alert.last_notified_date = on_date
            alert.save(update_fields=["last_notified_date"])
            sent += 1

    logger.info("Алерты: отправлено писем %d на %s", sent, on_date)
    return sent


def _notify(alert: PriceAlert, current_price: Decimal, on_date: dt.date) -> bool:
    """Отправить письмо. True — если ушло (для отметки last_notified_date)."""
    subject = f"Цена на «{alert.product.name}» снизилась"
    body = (
        f"Текущая цена: {current_price} {alert.currency} "
        f"(ваш порог {alert.target_price} {alert.currency}), дата {on_date}."
    )
    # Сбой почты не должен валить проверку остальных алертов, НО причину надо
    # знать (иначе письма молча не уходят). Поэтому ловим сами и логируем,
    # а не глушим через fail_silently=True.
    try:
        sent = send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [alert.user.email])
    except Exception:
        logger.exception("Не удалось отправить алерт user=%s product=%s", alert.user_id,
                         alert.product_id)
        return False
    return bool(sent)
