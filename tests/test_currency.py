"""Контракт сервиса конвертации валют (исторический курс, carry-forward).

Тестер-подход: проверяем НАБЛЮДАЕМЫЙ контракт `conversion_factor` конкретными
числами, посчитанными вручную от определения курса НБУ (rate = сколько UAH за 1
единицу валюты). Эталон НЕ получаем повторным вызовом прод-логики.

Сквозную «цену, как её видит пользователь» (сумма × множитель → округление до
сотых) проверяет `test_api` через реальный HTTP-эндпоинт — там проходит прод-путь
целиком, а не его копия в тесте.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.currency.models import CurrencyRate
from apps.currency.services import RateUnavailable, conversion_factor, supported_currencies

pytestmark = pytest.mark.django_db

DAY = dt.date(2026, 6, 1)


def _rate(code: str, day: dt.date, val: str) -> None:
    CurrencyRate.objects.create(code=code, rate_date=day, rate_uah=Decimal(val))


def test_usd_factor_is_identity_without_any_rate():
    """USD — базовая валюта: множитель ровно 1 и курс для этого не нужен."""
    assert conversion_factor("USD", DAY) == Decimal("1")


def test_uah_factor_equals_stored_usd_rate():
    """UAH за 1 USD — это и есть курс USD из НБУ."""
    _rate("USD", DAY, "40")
    assert conversion_factor("UAH", DAY) == Decimal("40")


def test_third_currency_is_cross_rate_through_uah():
    """EUR за 1 USD = rate(USD)/rate(EUR) — кросс-курс через гривну."""
    _rate("USD", DAY, "40")
    _rate("EUR", DAY, "43.5")
    # эталон считаем независимой арифметикой от определения, не прод-функцией
    assert conversion_factor("EUR", DAY) == Decimal("40") / Decimal("43.5")


def test_factor_uses_that_days_rate_not_todays():
    """Смысл задания: множитель привязан к ДАТЕ — разные дни → разные курсы."""
    d1, d2 = dt.date(2026, 6, 1), dt.date(2026, 6, 2)
    _rate("USD", d1, "40")
    _rate("USD", d2, "41")
    assert conversion_factor("UAH", d1) == Decimal("40")
    assert conversion_factor("UAH", d2) == Decimal("41")


def test_carry_forward_uses_nearest_earlier_rate_on_weekend():
    """НБУ не публикует курс в выходной → берём ближайший более ранний рабочий день."""
    monday = dt.date(2026, 6, 1)
    _rate("USD", monday, "40")
    saturday = dt.date(2026, 6, 6)
    assert conversion_factor("UAH", saturday) == Decimal("40")


def test_no_future_rate_leaks_backwards():
    """Курс будущего дня НЕ должен применяться к более ранней дате."""
    _rate("USD", dt.date(2026, 6, 10), "50")
    with pytest.raises(RateUnavailable):
        conversion_factor("UAH", dt.date(2026, 6, 1))


def test_missing_rate_raises_rather_than_guessing():
    with pytest.raises(RateUnavailable):
        conversion_factor("UAH", dt.date(2020, 1, 1))


def test_supported_currencies_always_include_usd_and_uah():
    """Без единого курса в БД USD и UAH всё равно поддержаны (база и целевая)."""
    assert set(supported_currencies()) >= {"USD", "UAH"}
    _rate("EUR", DAY, "43.5")
    assert "EUR" in supported_currencies()


# --- backfill истории курсов -------------------------------------------------

def _patch_provider(monkeypatch, behaviour):
    """Подменить провайдера НБУ; behaviour(on_date) → список DTO или исключение."""
    import apps.currency.tasks as ctasks

    class FakeProvider:
        def get_rates(self, on_date):
            return behaviour(on_date)

    monkeypatch.setattr(ctasks, "get_currency_provider", lambda *a, **k: FakeProvider())


def test_backfill_loads_missing_days_and_skips_existing(monkeypatch):
    """Догружает недостающие дни и не дёргает НБУ за уже загруженные."""
    import datetime as _dt

    from apps.currency.tasks import backfill_currency_rates
    from apps.integrations.currency.base import CurrencyRateDTO

    calls: list[_dt.date] = []

    def behaviour(on_date):
        calls.append(on_date)
        return [CurrencyRateDTO(code="USD", rate_date=on_date, rate_uah=Decimal("40"))]

    _patch_provider(monkeypatch, behaviour)
    today = dt.date.today()
    _rate("USD", today, "39")  # за сегодня уже есть → пропускается

    saved = backfill_currency_rates.run(days=3)
    assert saved == 2                       # today пропущен, загружены 2 прошлых дня
    assert today not in calls
    assert CurrencyRate.objects.filter(code="USD").count() == 3


def test_backfill_skips_failing_day_and_continues(monkeypatch):
    """Сбой НБУ на одном дне не обрывает догон — остальные дни грузятся."""
    import datetime as _dt

    from apps.currency.tasks import backfill_currency_rates
    from apps.integrations.currency.base import CurrencyRateDTO, IntegrationError

    today = dt.date.today()
    broken = today - _dt.timedelta(days=1)

    def behaviour(on_date):
        if on_date == broken:
            raise IntegrationError("НБУ лёг на этот день")
        return [CurrencyRateDTO(code="USD", rate_date=on_date, rate_uah=Decimal("40"))]

    _patch_provider(monkeypatch, behaviour)

    saved = backfill_currency_rates.run(days=3)
    assert saved == 2                                  # 3 дня минус один битый
    assert not CurrencyRate.objects.filter(rate_date=broken).exists()
    assert CurrencyRate.objects.filter(rate_date=today).exists()
