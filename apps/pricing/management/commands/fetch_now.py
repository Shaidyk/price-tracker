"""Синхронно выполнить сбор курсов и цен (без ожидания Celery Beat).

Удобно для разработки/демо: дёргает реальные API НБУ и магазинов, пишет цены за
сегодня и пересчитывает агрегаты. Сетевые сбои логируются, но команда не падает.
"""

from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.alerts.tasks import check_price_alerts
from apps.catalog.models import Offer, Shop
from apps.currency.tasks import backfill_currency_rates, fetch_currency_rates
from apps.integrations.shops.base import IntegrationError
from apps.integrations.shops.registry import get_shop_client
from apps.pricing.services import recompute_daily_stats, record_price


class Command(BaseCommand):
    help = "Живой сбор курсов и цен на сегодня (синхронно)."

    def handle(self, *args, **options) -> None:
        today = dt.date.today()

        # 1) курсы НБУ: сегодня + догрузка истории за окно тренда (для графика).
        # Без бэкфилла прошлые даты конвертировались бы неверно (см. backfill_currency_rates).
        try:
            n = fetch_currency_rates.run(date_iso=today.isoformat())
            b = backfill_currency_rates.run(days=settings.TREND_WINDOW_DAYS)
            self.stdout.write(f"Курсов загружено: сегодня {n}, история {b}")
        except Exception as exc:  # noqa: BLE001
            self.stderr.write(f"Курсы НБУ недоступны: {exc}")

        # 2) цены по активным магазинам
        for shop in Shop.objects.filter(is_active=True):
            try:
                client = get_shop_client(shop.code)
                products = client.fetch_products()
            except IntegrationError as exc:
                self.stderr.write(f"Магазин {shop.code} недоступен: {exc}")
                continue
            price_by_external = {p.external_id: p.price_usd for p in products}
            offers = Offer.objects.filter(shop=shop, is_active=True)
            saved = 0
            for offer in offers:
                price = price_by_external.get(offer.external_id)
                if price is not None:
                    record_price(offer, price, today)
                    saved += 1
            self.stdout.write(f"Магазин {shop.code}: записано цен {saved}")

        # 3) агрегаты + алерты
        updated = recompute_daily_stats(today)
        self.stdout.write(f"Пересчитано товаров: {updated}")
        check_price_alerts.run(date_iso=today.isoformat())
        self.stdout.write(self.style.SUCCESS("Готово."))
