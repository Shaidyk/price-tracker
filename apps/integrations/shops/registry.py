"""Реестр + фабрика адаптеров магазинов (Open-Closed).

Новый магазин = новый файл-адаптер + строка ``@register``. Ядро и другие
адаптеры не меняются. ``get_shop_client`` — единственная точка создания клиента.
"""

from __future__ import annotations

from apps.integrations.shops.base import ShopClient

SHOP_CLIENTS: dict[str, type[ShopClient]] = {}


def register(cls: type[ShopClient]) -> type[ShopClient]:
    """Декоратор: регистрирует адаптер по ``cls.code``.

    Дубль кода — ошибка конфигурации (две реализации на один магазин).
    """
    code = getattr(cls, "code", None)
    if not code:
        raise ValueError(f"{cls.__name__} must define a non-empty `code`")
    if code in SHOP_CLIENTS:
        raise ValueError(
            f"Shop code {code!r} already registered by "
            f"{SHOP_CLIENTS[code].__name__}"
        )
    SHOP_CLIENTS[code] = cls
    return cls


def get_shop_client(code: str) -> ShopClient:
    """Фабрика: создать экземпляр адаптера по коду магазина."""
    try:
        cls = SHOP_CLIENTS[code]
    except KeyError as exc:
        known = ", ".join(sorted(SHOP_CLIENTS)) or "<none>"
        raise ValueError(
            f"Unknown shop code {code!r}. Registered: {known}"
        ) from exc
    return cls()


def available_codes() -> list[str]:
    """Коды всех зарегистрированных магазинов (отсортированы)."""
    return sorted(SHOP_CLIENTS)


# Импорт адаптеров в самом конце — чтобы их @register сработал при импорте
# реестра, но не создавал циклической зависимости (адаптеры импортируют register).
from apps.integrations.shops import dummyjson, fakestore  # noqa: E402,F401
