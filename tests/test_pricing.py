"""Агрегаты дня и признак тренда + идемпотентность записи цены.

Тренд — сравнение цены сегодня со СРЕДНЕЙ за предыдущие 30 дней. Проверяем именно
это поведение (в т.ч. что сравнивается со средним, а не с последним днём), а не
внутреннюю реализацию. Всё в USD — валюта на тренд влиять не должна.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.catalog.models import Offer, Shop
from apps.pricing.models import PriceRecord, ProductDailyStat, Trend
from apps.pricing.services import recompute_daily_stats, record_price

pytestmark = pytest.mark.django_db

BASE = dt.date(2026, 6, 1)


def test_record_price_is_idempotent_per_offer_day(offer):
    """Повторная запись цены за тот же день перезаписывает, а не плодит строки."""
    record_price(offer, Decimal("10"), BASE)
    record_price(offer, Decimal("12"), BASE)
    qs = PriceRecord.objects.filter(offer=offer, date=BASE)
    assert qs.count() == 1
    assert qs.get().price_usd == Decimal("12")


def test_daily_stat_aggregates_min_max_avg_across_shops(product):
    """Диапазон от/до и средняя считаются по всем активным предложениям товара."""
    s1 = Shop.objects.create(code="a", name="A")
    s2 = Shop.objects.create(code="b", name="B")
    o1 = Offer.objects.create(product=product, shop=s1, external_id="1")
    o2 = Offer.objects.create(product=product, shop=s2, external_id="2")
    record_price(o1, Decimal("10"), BASE)
    record_price(o2, Decimal("20"), BASE)
    recompute_daily_stats(BASE)
    stat = ProductDailyStat.objects.get(product=product, date=BASE)
    assert (stat.min_price_usd, stat.max_price_usd, stat.avg_price_usd) == (
        Decimal("10"), Decimal("20"), Decimal("15"),
    )


def _history(offer, prices: list[Decimal]) -> ProductDailyStat:
    """Записать цены по дням начиная с BASE и пересчитать агрегаты; вернуть последний."""
    last = BASE
    for i, price in enumerate(prices):
        last = BASE + dt.timedelta(days=i)
        record_price(offer, price, last)
        recompute_daily_stats(last)
    return ProductDailyStat.objects.get(product=offer.product, date=last)


def test_trend_up_when_today_above_30day_average(offer):
    assert _history(offer, [Decimal("10")] * 30 + [Decimal("20")]).trend == Trend.UP


def test_trend_down_when_today_below_30day_average(offer):
    assert _history(offer, [Decimal("20")] * 30 + [Decimal("10")]).trend == Trend.DOWN


def test_trend_same_when_today_equals_average(offer):
    assert _history(offer, [Decimal("10")] * 31).trend == Trend.SAME


def test_trend_compares_to_average_not_to_last_day(offer):
    """Предыдущие дни [10, 30] (среднее 20), сегодня 20 → SAME.

    Если бы сравнивали с ПОСЛЕДНИМ днём (30), получили бы DOWN — ловим эту ошибку.
    """
    assert _history(offer, [Decimal("10"), Decimal("30"), Decimal("20")]).trend == Trend.SAME


def test_trend_same_on_first_day_no_history(offer):
    """Первый день сравнивать не с чем → SAME, а не выдуманный рост."""
    record_price(offer, Decimal("10"), BASE)
    recompute_daily_stats(BASE)
    assert ProductDailyStat.objects.get(product=offer.product, date=BASE).trend == Trend.SAME


def test_recompute_ignores_inactive_offers(product):
    """Снятое с продажи предложение не должно влиять на диапазон/среднюю."""
    s1 = Shop.objects.create(code="a", name="A")
    s2 = Shop.objects.create(code="b", name="B")
    active = Offer.objects.create(product=product, shop=s1, external_id="1")
    inactive = Offer.objects.create(product=product, shop=s2, external_id="2", is_active=False)
    record_price(active, Decimal("10"), BASE)
    record_price(inactive, Decimal("99"), BASE)
    recompute_daily_stats(BASE)
    stat = ProductDailyStat.objects.get(product=product, date=BASE)
    assert stat.max_price_usd == Decimal("10")
