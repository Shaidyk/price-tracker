"""Контракты слоя провайдеров валютных курсов.

Подключаемость как у магазинов (Strategy): источник курсов можно сменить, не
трогая ядро. Транспорт (HTTP + ошибки) — в общем `apps.integrations._http`.
"""

from __future__ import annotations

import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from apps.integrations._http import HttpClient, IntegrationError

__all__ = ["CurrencyRateDTO", "CurrencyProvider", "IntegrationError"]


@dataclass(frozen=True)
class CurrencyRateDTO:
    """Курс валюты на дату: ``rate_uah`` — UAH за 1 единицу валюты ``code``."""

    code: str
    rate_date: datetime.date
    rate_uah: Decimal


class CurrencyProvider(HttpClient, ABC):
    """Интерфейс источника валютных курсов."""

    code: str

    @abstractmethod
    def get_rates(self, on_date: datetime.date) -> list[CurrencyRateDTO]:
        """Курсы всех валют на дату ``on_date``."""
