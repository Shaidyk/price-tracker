"""Контракты слоя интеграции с магазинами.

Транспорт (HTTP + ошибки) — в общем `apps.integrations._http`; здесь только то,
что специфично магазинам: DTO товара и интерфейс адаптера.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from apps.integrations._http import HttpClient, IntegrationError

__all__ = ["ShopProductDTO", "ShopClient", "IntegrationError"]


@dataclass(frozen=True)
class ShopProductDTO:
    """Нормализованная форма товара из любого магазина.

    Цена всегда в USD и всегда Decimal (деньги — не float).
    """

    external_id: str
    title: str
    description: str
    price_usd: Decimal


class ShopClient(HttpClient, ABC):
    """Интерфейс адаптера магазина (паттерн Adapter + Factory через registry).

    Конкретные адаптеры приводят разную форму ответа API к ShopProductDTO.
    """

    code: str

    @abstractmethod
    def fetch_products(self) -> list[ShopProductDTO]:
        """Все товары магазина в нормализованной форме."""
