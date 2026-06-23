"""Конвертация денег по курсам НБУ (rate = UAH за 1 единицу валюты).

USD→target на дату d: amount_usd * rate(USD, d) / rate(target, d). Курс берём на d
или ближайший более ранний (carry-forward на выходные). Курса нет → RateUnavailable.
"""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings

from .models import CurrencyRate

UAH = "UAH"
_CENTS = Decimal("0.01")


class RateUnavailable(Exception):
    """Нет курса для запрошенной валюты на дату (и ранее)."""


def _get_rate(code: str, on_date: dt.date) -> Decimal:
    """UAH за 1 единицу `code` на дату `on_date` (или ближайшую ранее).

    UAH к самой себе = 1. Поиск по индексу (code, -rate_date).
    """
    if code == UAH:
        return Decimal("1")
    rate = (
        CurrencyRate.objects.filter(code=code, rate_date__lte=on_date)
        .order_by("-rate_date")
        .values_list("rate_uah", flat=True)
        .first()
    )
    if rate is None:
        raise RateUnavailable(f"Нет курса {code} на {on_date} или ранее")
    if rate <= 0:
        # подстраховка: на нулевой/отрицательный курс делить нельзя
        raise RateUnavailable(f"Некорректный курс {code} на {on_date}: {rate}")
    return rate


def conversion_factor(to_code: str, on_date: dt.date) -> Decimal:
    """Множитель перевода суммы из USD в `to_code` на дату `on_date`.

    Конвертация линейна: target = amount_usd * factor. Считаем факт-курсы один раз,
    чтобы конвертировать целую страницу списка без N+1 запросов к курсам.
        USD  → 1
        UAH  → rate(USD)
        иное → rate(USD) / rate(target)
    """
    base = settings.BASE_CURRENCY  # USD
    if to_code == base:
        return Decimal("1")
    rate_usd = _get_rate(base, on_date)
    if to_code == UAH:
        return rate_usd
    return rate_usd / _get_rate(to_code, on_date)


def factors_for_dates(to_code: str, dates: list[dt.date]) -> dict[dt.date, Decimal]:
    """Множители USD→`to_code` для набора дат (исторические курсы).

    Считаем по одному множителю на УНИКАЛЬНУЮ дату — это и есть конвертация истории
    «курсом того дня». Кэш по дате, чтобы не пересчитывать повторяющиеся даты.
    """
    cache: dict[dt.date, Decimal] = {}
    for d in dates:
        if d not in cache:
            cache[d] = conversion_factor(to_code, d)
    return cache


def quantize_money(amount: Decimal) -> Decimal:
    """Округлить до сотых (ROUND_HALF_UP) — отображаемая цена.

    Конвертация в коде идёт через `conversion_factor` (один множитель на дату для
    списка/детали/цен) и `factors_for_dates` (множитель на каждую дату для истории).
    """
    return amount.quantize(_CENTS, rounding=ROUND_HALF_UP)


def supported_currencies() -> list[str]:
    """Валюты, для которых у нас есть хотя бы один курс (+ USD и UAH всегда)."""
    qs = CurrencyRate.objects.values_list("code", flat=True).distinct()
    codes = set(qs) | {settings.BASE_CURRENCY, UAH}
    return sorted(codes)
