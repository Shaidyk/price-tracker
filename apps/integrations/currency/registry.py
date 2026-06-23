"""Реестр + фабрика провайдеров валютных курсов (как у магазинов).

Симметрично shops/registry: новый источник курсов = новый адаптер + ``@register`` +
(опционально) DEFAULT_CURRENCY_PROVIDER в настройках. Ядро не меняется.
"""

from __future__ import annotations

from apps.integrations.currency.base import CurrencyProvider

CURRENCY_PROVIDERS: dict[str, type[CurrencyProvider]] = {}
_DEFAULT = "nbu"


def register(cls: type[CurrencyProvider]) -> type[CurrencyProvider]:
    code = getattr(cls, "code", None)
    if not code:
        raise ValueError(f"{cls.__name__} must define a non-empty `code`")
    if code in CURRENCY_PROVIDERS:
        raise ValueError(f"Currency provider {code!r} already registered")
    CURRENCY_PROVIDERS[code] = cls
    return cls


def get_currency_provider(code: str | None = None) -> CurrencyProvider:
    """Фабрика провайдера. По умолчанию — DEFAULT_CURRENCY_PROVIDER (или 'nbu')."""
    if code is None:
        from django.conf import settings

        code = getattr(settings, "DEFAULT_CURRENCY_PROVIDER", _DEFAULT)
    try:
        cls = CURRENCY_PROVIDERS[code]
    except KeyError as exc:
        known = ", ".join(sorted(CURRENCY_PROVIDERS)) or "<none>"
        raise ValueError(f"Unknown currency provider {code!r}. Registered: {known}") from exc
    return cls()


def available_codes() -> list[str]:
    return sorted(CURRENCY_PROVIDERS)


# Импорт адаптеров в конце — чтобы их @register сработал при импорте реестра.
from apps.integrations.currency import nbu  # noqa: E402,F401
