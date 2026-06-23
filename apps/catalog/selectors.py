"""Чтение каталога для API: список, деталь, цены на сегодня, история.

Селекторы возвращают данные в USD (+ даты). Пересчёт в выбранную валюту — в слое
представления (views/serializers): для списка/детали одним множителем на дату,
для истории — курсом КАЖДОЙ даты (исторический курс).
Агрегаты берём из денормализованной ProductDailyStat, не из сырья.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.db.models import Case, IntegerField, QuerySet, Value, When

from apps.pricing.models import PriceRecord, ProductDailyStat, Trend

from .models import TrackedProduct

# Сортировка по тренду: рост «выше» падения. trend_rank up=2, same=1, down=0.
_TREND_RANK = Case(
    When(trend=Trend.UP, then=Value(2)),
    When(trend=Trend.SAME, then=Value(1)),
    When(trend=Trend.DOWN, then=Value(0)),
    output_field=IntegerField(),
)

def latest_stat_date() -> dt.date | None:
    """Самая свежая дата, на которую есть посчитанные агрегаты («сегодня» сервиса)."""
    return (
        ProductDailyStat.objects.order_by("-date")
        .values_list("date", flat=True)
        .first()
    )


def products_for_list(product_ids: set[int] | None = None) -> QuerySet[ProductDailyStat]:
    """Агрегаты товаров на последнюю дату; `product_ids` ограничивает watchlist'ом.

    Сортировку и keyset-пагинацию делает пагинатор по `trend_rank`/цене. Сортировать
    можно в USD: умножение на положительный курс порядок не меняет.
    """
    on_date = latest_stat_date()
    if on_date is None:
        return ProductDailyStat.objects.none()

    qs = ProductDailyStat.objects.filter(date=on_date)
    if product_ids is not None:
        qs = qs.filter(product_id__in=product_ids)
    return qs.select_related("product").annotate(trend_rank=_TREND_RANK)


def watchlist_product_ids(user) -> set[int]:
    """id товаров в списке отслеживания пользователя."""
    return set(
        TrackedProduct.objects.filter(user=user).values_list("product_id", flat=True)
    )


def latest_stat_for_product(product_id: int) -> ProductDailyStat | None:
    return (
        ProductDailyStat.objects.filter(product_id=product_id)
        .order_by("-date")
        .first()
    )


def today_prices_per_shop(product_id: int, on_date: dt.date) -> list[dict]:
    """Пары «магазин — цена (USD)» за день для опции «Отобразить все цены»."""
    records = (
        PriceRecord.objects.filter(
            offer__product_id=product_id, offer__is_active=True, date=on_date
        )
        .select_related("offer__shop")
        .order_by("price_usd")
    )
    return [
        {
            "shop_code": r.offer.shop.code,
            "shop_name": r.offer.shop.name,
            "price_usd": r.price_usd,
            "date": r.date,
        }
        for r in records
    ]


def price_history(
    product_id: int,
    shop_code: str | None,
    date_from: dt.date | None,
    date_to: dt.date | None,
) -> dict:
    """История цен для графика: серии по магазинам + серия средней цены (всё в USD).

    Возвращает {"shops": {code: [(date, price_usd)]}, "average": [(date, avg_usd)]}.
    Конвертацию по историческому курсу делает слой представления.

    Без `date_from`/`date_to` отдаётся вся история — на годах данных это тяжёлый
    ответ, поэтому клиент графика обычно передаёт диапазон. При больших объёмах
    стоит ввести дефолтное окно и/или даунсэмплинг по неделям.
    """
    records = PriceRecord.objects.filter(
        offer__product_id=product_id, offer__is_active=True
    ).select_related("offer__shop")
    if shop_code:
        records = records.filter(offer__shop__code=shop_code)
    if date_from:
        records = records.filter(date__gte=date_from)
    if date_to:
        records = records.filter(date__lte=date_to)
    records = records.order_by("date")

    shops: dict[str, list[tuple[dt.date, Decimal]]] = {}
    for r in records:
        shops.setdefault(r.offer.shop.code, []).append((r.date, r.price_usd))

    # средняя цена по дням — из агрегатов (дёшево и согласованно со списком)
    avg_qs = ProductDailyStat.objects.filter(product_id=product_id)
    if date_from:
        avg_qs = avg_qs.filter(date__gte=date_from)
    if date_to:
        avg_qs = avg_qs.filter(date__lte=date_to)
    average = list(avg_qs.order_by("date").values_list("date", "avg_price_usd"))

    return {"shops": shops, "average": average}
