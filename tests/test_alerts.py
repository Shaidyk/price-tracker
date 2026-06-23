"""Тесты проверки алертов: отправка письма ниже порога и защита от спама."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core import mail

from apps.alerts.models import PriceAlert
from apps.alerts.tasks import check_price_alerts
from apps.currency.models import CurrencyRate
from apps.pricing.models import ProductDailyStat, Trend

pytestmark = pytest.mark.django_db


@pytest.fixture
def stat(product):
    day = dt.date(2026, 6, 1)
    ProductDailyStat.objects.create(
        product=product, date=day, min_price_usd=Decimal("10"),
        max_price_usd=Decimal("10"), avg_price_usd=Decimal("10"), trend=Trend.SAME,
    )
    CurrencyRate.objects.create(code="USD", rate_date=day, rate_uah=Decimal("40"))
    return day


def test_email_sent_when_below_threshold(user, product, stat):
    PriceAlert.objects.create(
        user=user, product=product, target_price=Decimal("15"), currency="USD"
    )
    sent = check_price_alerts.run(date_iso=stat.isoformat())
    assert sent == 1
    assert len(mail.outbox) == 1
    assert user.email in mail.outbox[0].to


def test_no_email_when_above_threshold(user, product, stat):
    PriceAlert.objects.create(user=user, product=product, target_price=Decimal("5"), currency="USD")
    assert check_price_alerts.run(date_iso=stat.isoformat()) == 0
    assert mail.outbox == []


def test_no_email_when_price_equals_threshold(user, product, stat):
    """Цена ровно равна порогу — это ещё не «ниже», письма нет."""
    PriceAlert.objects.create(
        user=user, product=product, target_price=Decimal("10"), currency="USD"
    )
    assert check_price_alerts.run(date_iso=stat.isoformat()) == 0
    assert mail.outbox == []


def test_no_double_notification_same_day(user, product, stat):
    PriceAlert.objects.create(
        user=user, product=product, target_price=Decimal("15"), currency="USD"
    )
    check_price_alerts.run(date_iso=stat.isoformat())
    mail.outbox.clear()
    # повторный прогон в тот же день — письма быть не должно
    assert check_price_alerts.run(date_iso=stat.isoformat()) == 0
    assert mail.outbox == []


def test_threshold_in_alert_currency(user, product, stat):
    """target в UAH: 10 USD = 400 UAH, порог 500 UAH → срабатывает (курс USD из фикстуры)."""
    PriceAlert.objects.create(
        user=user, product=product, target_price=Decimal("500"), currency="UAH"
    )
    assert check_price_alerts.run(date_iso=stat.isoformat()) == 1
