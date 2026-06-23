"""Слой интеграций (apps.integrations) — чёрный ящик через замоканный HTTP.

Проверяем и нормализацию ответа, и КАК клиент дёргает внешний API (URL + query):
именно параметры запроса (`?limit=0`, `?date=YYYYMMDD&json`) ломаются против
реального сервиса. Реальной сети нет.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
import responses

from apps.integrations.currency.base import CurrencyRateDTO
from apps.integrations.currency.nbu import NbuCurrencyProvider
from apps.integrations.shops.base import IntegrationError, ShopProductDTO
from apps.integrations.shops.dummyjson import DummyJsonClient
from apps.integrations.shops.fakestore import FakeStoreClient
from apps.integrations.shops.registry import available_codes, get_shop_client

DUMMYJSON = "https://dummyjson.com/products"
FAKESTORE = "https://fakestoreapi.com/products"
NBU = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"


# --- dummyjson: запрос + нормализация ----------------------------------------
@responses.activate
def test_dummyjson_requests_full_list_without_pagination():
    """Клиент обязан звать ?limit=0 — иначе dummyjson отдаст лишь первую страницу."""
    responses.add(
        responses.GET, DUMMYJSON,
        json={"products": [{"id": 1, "title": "Phone", "description": "n", "price": 9.99}]},
        status=200,
        match=[responses.matchers.query_param_matcher({"limit": "0"})],
    )
    products = DummyJsonClient(timeout=10).fetch_products()
    assert [(p.external_id, p.title, p.price_usd) for p in products] == [
        ("1", "Phone", Decimal("9.99"))
    ]
    assert isinstance(products[0].price_usd, Decimal)


@responses.activate
def test_dummyjson_skips_malformed_items_but_keeps_good():
    responses.add(
        responses.GET, DUMMYJSON,
        json={"products": [
            {"id": 1, "title": "Good", "description": "d", "price": 5},
            {"id": 2, "title": "NoPrice", "description": "d"},  # нет цены
            "not-an-object",
        ]},
        status=200,
    )
    products = DummyJsonClient(timeout=10).fetch_products()
    assert [p.external_id for p in products] == ["1"]


# --- fakestore ---------------------------------------------------------------
@responses.activate
def test_fakestore_normalizes_root_list():
    responses.add(
        responses.GET, FAKESTORE,
        json=[
            {"id": 1, "title": "Bag", "price": 12.3, "description": "leather"},
            {"id": 2, "title": "Shoes", "price": 49, "description": "sport"},
        ],
        status=200,
    )
    products = FakeStoreClient(timeout=10).fetch_products()
    assert [p.price_usd for p in products] == [Decimal("12.3"), Decimal("49")]
    assert all(isinstance(p, ShopProductDTO) for p in products)


# --- обработка ошибок: мусор наружу не утекает -------------------------------
@responses.activate
def test_non_json_body_raises_integration_error():
    responses.add(responses.GET, DUMMYJSON, body="<html>", status=200, content_type="text/html")
    with pytest.raises(IntegrationError):
        DummyJsonClient(timeout=10).fetch_products()


@responses.activate
def test_non_2xx_raises_integration_error():
    responses.add(responses.GET, FAKESTORE, status=404)
    with pytest.raises(IntegrationError):
        FakeStoreClient(timeout=10).fetch_products()


# --- НБУ: запрос на конкретную дату + парсинг --------------------------------
@responses.activate
def test_nbu_requests_rates_for_the_given_date():
    """URL обязан нести дату в формате YYYYMMDD и флаг json."""
    on_date = datetime.date(2024, 1, 15)
    responses.add(
        responses.GET, NBU,
        json=[{"r030": 840, "txt": "Долар США", "rate": 37.5, "cc": "USD",
               "exchangedate": "15.01.2024"}],
        status=200,
        match=[responses.matchers.query_string_matcher("date=20240115&json")],
    )
    rates = NbuCurrencyProvider(timeout=10).get_rates(on_date)
    usd = next(r for r in rates if r.code == "USD")
    assert usd.rate_uah == Decimal("37.5")
    assert usd.rate_date == on_date
    assert isinstance(usd.rate_uah, Decimal)


@responses.activate
def test_nbu_drops_non_positive_rate_as_garbage():
    """Нулевой/отрицательный курс — мусор (на него делят), не должен попасть в DTO."""
    responses.add(
        responses.GET, NBU,
        json=[
            {"cc": "USD", "rate": 37.5, "exchangedate": "15.01.2024"},
            {"cc": "XXX", "rate": 0, "exchangedate": "15.01.2024"},
        ],
        status=200,
    )
    rates = NbuCurrencyProvider(timeout=10).get_rates(datetime.date(2024, 1, 15))
    assert [r.code for r in rates] == ["USD"]
    assert all(isinstance(r, CurrencyRateDTO) for r in rates)


@responses.activate
def test_nbu_empty_response_is_not_an_error():
    """Выходной/праздник → НБУ отдаёт []; это норма, не исключение."""
    responses.add(responses.GET, NBU, json=[], status=200)
    assert NbuCurrencyProvider(timeout=10).get_rates(datetime.date(2024, 1, 13)) == []


@responses.activate
def test_nbu_non_2xx_raises_integration_error():
    responses.add(responses.GET, NBU, status=500)
    with pytest.raises(IntegrationError):
        NbuCurrencyProvider(timeout=10).get_rates(datetime.date(2024, 1, 15))


# --- реестр магазинов: подключаемость ----------------------------------------
def test_registry_resolves_registered_shops():
    assert isinstance(get_shop_client("dummyjson"), DummyJsonClient)
    assert isinstance(get_shop_client("fakestore"), FakeStoreClient)


def test_registry_unknown_code_raises():
    with pytest.raises(ValueError):
        get_shop_client("nope")


def test_registry_lists_available_shops():
    assert {"dummyjson", "fakestore"} <= set(available_codes())
