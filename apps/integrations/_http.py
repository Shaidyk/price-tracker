"""Общий HTTP-транспорт интеграций: таймаут, ретраи, JSON, IntegrationError.

Здесь, чтобы магазины и провайдеры валют не импортировали друг друга. Не зависит
от Django ORM — работает и в изолированных юнит-тестах.
"""

from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class IntegrationError(Exception):
    """Любой сбой обращения к внешней системе (сеть, не-2xx, не-JSON)."""


def _default_timeout() -> float:
    """Таймаут внешних вызовов из Django settings с дефолтом 10 секунд.

    Импорт ленивый: слой интеграций должен работать и без настроенного Django.
    """
    try:
        from django.conf import settings

        return float(getattr(settings, "HTTP_TIMEOUT", 10))
    except Exception:
        return 10.0


def _build_session() -> requests.Session:
    """Session с ретраями на сетевые сбои и 5xx/429."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.3,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class HttpClient:
    """Базовый HTTP-клиент: таймаут, ретраи, JSON с оборачиванием ошибок.

    Адаптеры магазинов и валютных провайдеров наследуют его, добавляя свои
    абстрактные методы — общий транспорт не дублируется.
    """

    def __init__(self, timeout: float | None = None) -> None:
        self._timeout = timeout if timeout is not None else _default_timeout()
        self._session = _build_session()

    def _get_json(self, url: str) -> Any:
        """GET ``url`` с таймаутом и ретраями, вернуть распарсенный JSON.

        Сетевой сбой, не-2xx или не-JSON ответ → IntegrationError.
        """
        try:
            response = self._session.get(url, timeout=self._timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise IntegrationError(f"HTTP request to {url} failed: {exc}") from exc

        try:
            return response.json()
        except ValueError as exc:
            raise IntegrationError(f"Non-JSON response from {url}: {exc}") from exc
