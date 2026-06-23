"""Запись сырых цен и пересчёт дневных агрегатов с трендом.

Тренд считаем в USD (сегодняшняя средняя vs средняя за TREND_WINDOW_DAYS дней): в
валюте показа девальвация дала бы ложный «рост» по всем товарам.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.conf import settings
from django.db.models import Avg, Max, Min

from apps.catalog.models import Offer

from .models import PriceRecord, ProductDailyStat, Trend


def _pct_change(current: float, baseline: float) -> float:
    """Процентное изменение `current` относительно `baseline` (0 при baseline==0)."""
    return 0.0 if not baseline else (current - baseline) / baseline * 100.0


def record_price(offer: Offer, price_usd: Decimal, on_date: dt.date) -> PriceRecord:
    """Идемпотентно сохранить цену предложения за день (upsert по offer+date)."""
    record, _ = PriceRecord.objects.update_or_create(
        offer=offer, date=on_date, defaults={"price_usd": price_usd}
    )
    return record


def _trend_for(today_avg: Decimal, prev_avg: Decimal | None) -> str:
    """Определить тренд по сегодняшней средней и средней за окно (обе в USD)."""
    if prev_avg is None or prev_avg == 0:
        return Trend.SAME  # нечего сравнивать — не выдумываем рост/падение
    change = _pct_change(float(today_avg), float(prev_avg))
    threshold = settings.TREND_EPSILON * 100.0
    if change > threshold:
        return Trend.UP
    if change < -threshold:
        return Trend.DOWN
    return Trend.SAME


def recompute_daily_stats(on_date: dt.date) -> int:
    """Пересчитать ProductDailyStat по сырью за `on_date`.

    Агрегация (Min/Max/Avg) выполняется в БД, не в Python — важно для масштаба.
    Возвращает число обновлённых товаров.
    """
    window_start = on_date - dt.timedelta(days=settings.TREND_WINDOW_DAYS)

    # min/max/avg цены по товару за день (только активные предложения)
    rows = (
        PriceRecord.objects.filter(date=on_date, offer__is_active=True)
        .values("offer__product")
        .annotate(
            min_p=Min("price_usd"),
            max_p=Max("price_usd"),
            avg_p=Avg("price_usd"),
        )
    )

    # Средняя за предыдущие N дней — ОДНИМ групповым запросом по всем товарам сразу
    # (а не по запросу на товар: иначе N+1 на миллионах товаров).
    prev_avgs = {
        r["product_id"]: r["a"]
        for r in (
            ProductDailyStat.objects.filter(date__gte=window_start, date__lt=on_date)
            .values("product_id")
            .annotate(a=Avg("avg_price_usd"))
        )
    }

    updated = 0
    for row in rows:
        product_id = row["offer__product"]
        today_avg = row["avg_p"]
        prev_avg = prev_avgs.get(product_id)

        ProductDailyStat.objects.update_or_create(
            product_id=product_id,
            date=on_date,
            defaults={
                "min_price_usd": row["min_p"],
                "max_price_usd": row["max_p"],
                "avg_price_usd": today_avg,
                "trend": _trend_for(today_avg, prev_avg),
            },
        )
        updated += 1
    return updated
