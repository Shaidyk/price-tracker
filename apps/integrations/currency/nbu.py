"""Провайдер валютных курсов НБУ (bank.gov.ua).

API отдаёт UAH за 1 единицу валюты. На выходные/праздники НБУ может вернуть
пустой список — это нормальный случай, возвращаем ``[]`` (carry-forward делает
вышестоящий сервис).
"""

from __future__ import annotations

import datetime
import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.integrations.currency.base import CurrencyProvider, CurrencyRateDTO
from apps.integrations.currency.registry import register

logger = logging.getLogger(__name__)

_BASE_URL = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"


@register
class NbuCurrencyProvider(CurrencyProvider):
    """Курсы НБУ на конкретную дату."""

    code = "nbu"

    def get_rates(self, on_date: datetime.date) -> list[CurrencyRateDTO]:
        url = f"{_BASE_URL}?date={on_date.strftime('%Y%m%d')}&json"
        data = self._get_json(url)

        if not isinstance(data, list):
            logger.warning("nbu: unexpected payload shape, expected a list")
            return []

        result: list[CurrencyRateDTO] = []
        for raw in data:
            dto = _to_dto(raw, on_date)
            if dto is not None:
                result.append(dto)
        return result


def _to_dto(raw: Any, on_date: datetime.date) -> CurrencyRateDTO | None:
    """Нормализовать одну запись НБУ в DTO; битая → ``None`` (с warning)."""
    if not isinstance(raw, dict):
        logger.warning("nbu: rate entry is not an object, skipped: %r", raw)
        return None
    try:
        code = str(raw["cc"])
        rate_uah = Decimal(str(raw["rate"]))
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        logger.warning("nbu: skipping malformed rate %r: %s", raw, exc)
        return None
    # Неположительный курс — это мусор (делить на него нельзя). Пропускаем.
    if rate_uah <= 0:
        logger.warning("nbu: skipping non-positive rate for %s: %s", code, rate_uah)
        return None
    return CurrencyRateDTO(code=code, rate_date=on_date, rate_uah=rate_uah)
