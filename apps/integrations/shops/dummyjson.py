"""Адаптер магазина dummyjson.com.

Форма ответа списка — ``{"products": [ {id, title, description, price, ...} ]}``.
Цена в этом источнике трактуется как USD.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.integrations.shops.base import ShopClient, ShopProductDTO
from apps.integrations.shops.registry import register

logger = logging.getLogger(__name__)

_BASE_URL = "https://dummyjson.com/products"


@register
class DummyJsonClient(ShopClient):
    code = "dummyjson"

    def fetch_products(self) -> list[ShopProductDTO]:
        # limit=0 → dummyjson отдаёт все товары без пагинации.
        data = self._get_json(f"{_BASE_URL}?limit=0")
        raw_products = data.get("products") if isinstance(data, dict) else None
        if not isinstance(raw_products, list):
            logger.warning("dummyjson: unexpected payload shape, no 'products' list")
            return []

        result: list[ShopProductDTO] = []
        for raw in raw_products:
            dto = _to_dto(raw)
            if dto is not None:
                result.append(dto)
        return result


def _to_dto(raw: Any) -> ShopProductDTO | None:
    """Нормализовать сырой товар в DTO; битый/неполный → ``None`` (с warning)."""
    if not isinstance(raw, dict):
        logger.warning("dummyjson: product is not an object, skipped: %r", raw)
        return None
    try:
        external_id = str(raw["id"])
        title = str(raw["title"])
        description = str(raw.get("description", ""))
        price_usd = Decimal(str(raw["price"]))
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        logger.warning("dummyjson: skipping malformed product %r: %s", raw, exc)
        return None
    return ShopProductDTO(
        external_id=external_id,
        title=title,
        description=description,
        price_usd=price_usd,
    )
