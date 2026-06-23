"""Адаптер магазина fakestoreapi.com.

Форма ответа списка — массив в корне: ``[ {id, title, price, description, ...} ]``.
Цена трактуется как USD.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.integrations.shops.base import ShopClient, ShopProductDTO
from apps.integrations.shops.registry import register

logger = logging.getLogger(__name__)

_BASE_URL = "https://fakestoreapi.com/products"


@register
class FakeStoreClient(ShopClient):
    code = "fakestore"

    def fetch_products(self) -> list[ShopProductDTO]:
        data = self._get_json(_BASE_URL)
        if not isinstance(data, list):
            logger.warning("fakestore: unexpected payload shape, expected a list")
            return []

        result: list[ShopProductDTO] = []
        for raw in data:
            dto = _to_dto(raw)
            if dto is not None:
                result.append(dto)
        return result


def _to_dto(raw: Any) -> ShopProductDTO | None:
    """Нормализовать сырой товар в DTO; битый/неполный → ``None`` (с warning)."""
    if not isinstance(raw, dict):
        logger.warning("fakestore: product is not an object, skipped: %r", raw)
        return None
    try:
        external_id = str(raw["id"])
        title = str(raw["title"])
        description = str(raw.get("description", ""))
        price_usd = Decimal(str(raw["price"]))
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        logger.warning("fakestore: skipping malformed product %r: %s", raw, exc)
        return None
    return ShopProductDTO(
        external_id=external_id,
        title=title,
        description=description,
        price_usd=price_usd,
    )
