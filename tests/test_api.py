"""API глазами пользователя (чёрный ящик).

Гоняем реальные HTTP-эндпоинты через APIClient; ожидаемые цены посчитаны вручную
(USD-цена × курс дня, округление до сотых), а не вызовом прод-конвертера. Так тест
ловит ошибку в самом прод-пути отображения, а не сверяет код сам с собой.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.catalog.models import Offer, Product, Shop, TrackedProduct
from apps.currency.models import CurrencyRate
from apps.pricing.models import ProductDailyStat, Trend
from apps.pricing.services import recompute_daily_stats, record_price

pytestmark = pytest.mark.django_db

DAY = dt.date(2026, 6, 1)


def _stat(product, *, mn, mx, avg, trend, day=DAY):
    return ProductDailyStat.objects.create(
        product=product, date=day,
        min_price_usd=Decimal(mn), max_price_usd=Decimal(mx),
        avg_price_usd=Decimal(avg), trend=trend,
    )


@pytest.fixture
def catalog():
    """Три товара с разной ценой и трендом на DAY + курс USD=40 UAH."""
    cheap = Product.objects.create(name="Cheap", description="дешёвый")
    mid = Product.objects.create(name="Mid", description="средний")
    pricey = Product.objects.create(name="Pricey", description="дорогой")
    _stat(cheap, mn="5", mx="5", avg="5", trend=Trend.DOWN)
    _stat(mid, mn="10", mx="12", avg="11", trend=Trend.SAME)
    _stat(pricey, mn="50", mx="60", avg="55", trend=Trend.UP)
    CurrencyRate.objects.create(code="USD", rate_date=DAY, rate_uah=Decimal("40"))
    return {"cheap": cheap, "mid": mid, "pricey": pricey}


# --- список товаров: поля, сортировки, валюта --------------------------------

def test_list_returns_today_price_range_and_trend(api, catalog):
    """Поля строки списка: имя, диапазон от/до на сегодня, признак тренда."""
    rows = {r["name"]: r for r in api.get("/api/products/?ordering=price").json()["results"]}
    pricey = rows["Pricey"]
    assert pricey["price_from"] == "50.00"
    assert pricey["price_to"] == "60.00"
    assert pricey["trend"] == "up"
    assert rows["Cheap"]["trend"] == "down"


def test_list_sorted_by_price_ascending_and_descending(api, catalog):
    asc = [r["name"] for r in api.get("/api/products/?ordering=price").json()["results"]]
    desc = [r["name"] for r in api.get("/api/products/?ordering=-price").json()["results"]]
    assert asc == ["Cheap", "Mid", "Pricey"]
    assert desc == ["Pricey", "Mid", "Cheap"]


def test_list_sorted_by_trend_full_order_growth_first(api, catalog):
    """Сортировка по тенденции: -trend = рост→ровно→падение, trend — наоборот."""
    desc = [r["name"] for r in api.get("/api/products/?ordering=-trend").json()["results"]]
    asc = [r["name"] for r in api.get("/api/products/?ordering=trend").json()["results"]]
    assert desc == ["Pricey", "Mid", "Cheap"]   # up, same, down
    assert asc == ["Cheap", "Mid", "Pricey"]     # down, same, up


def test_list_prices_converted_to_requested_currency(api, catalog):
    first = api.get("/api/products/?currency=UAH&ordering=price").json()["results"][0]
    assert first["name"] == "Cheap"
    assert first["currency"] == "UAH"
    assert first["price_from"] == "200.00"   # 5 USD * 40
    assert first["price_to"] == "200.00"


def test_list_conversion_to_third_currency_rounds_to_cents(api, catalog):
    """EUR через кросс-курс: 5 USD * (40/43.5) = 4.5977 → 4.60."""
    CurrencyRate.objects.create(code="EUR", rate_date=DAY, rate_uah=Decimal("43.5"))
    first = api.get("/api/products/?currency=EUR&ordering=price").json()["results"][0]
    assert first["currency"] == "EUR"
    assert first["price_from"] == "4.60"


def test_list_unknown_currency_is_rejected(api, catalog):
    assert api.get("/api/products/?currency=GBP").status_code == 400


def test_list_keyset_pagination_walks_all_pages(api, catalog):
    """Курсор-пагинация: страница + ссылка next, по которой добираем остальное."""
    p1 = api.get("/api/products/?ordering=price&page_size=2").json()
    assert [r["name"] for r in p1["results"]] == ["Cheap", "Mid"]
    assert p1["next"] is not None
    p2 = api.get(p1["next"]).json()
    assert [r["name"] for r in p2["results"]] == ["Pricey"]
    assert p2["next"] is None


def test_list_default_currency_is_usd(api, catalog):
    first = api.get("/api/products/?ordering=price").json()["results"][0]
    assert first["currency"] == "USD"
    assert first["price_from"] == "5.00"


# --- деталь товара -----------------------------------------------------------

def test_detail_has_name_description_range_trend(api, catalog):
    pid = catalog["pricey"].id
    body = api.get(f"/api/products/{pid}/?currency=UAH").json()
    assert body["name"] == "Pricey"
    assert body["description"] == "дорогой"
    assert body["price_from"] == "2000.00"   # 50*40
    assert body["price_to"] == "2400.00"     # 60*40
    assert body["trend"] == "up"


def test_detail_unknown_product_is_404(api, catalog):
    assert api.get("/api/products/999999/").status_code == 404


# --- «Отобразить все цены»: пары магазин-цена на сегодня ---------------------

def test_all_prices_lists_each_shop_price_today_converted(api, product):
    """Опция «все цены»: список пар магазин→цена за сегодня в выбранной валюте."""
    shop_a = Shop.objects.create(code="a", name="A-shop")
    shop_b = Shop.objects.create(code="b", name="B-shop")
    off_a = Offer.objects.create(product=product, shop=shop_a, external_id="1")
    off_b = Offer.objects.create(product=product, shop=shop_b, external_id="2")
    record_price(off_a, Decimal("50"), DAY)
    record_price(off_b, Decimal("60"), DAY)
    recompute_daily_stats(DAY)
    CurrencyRate.objects.create(code="USD", rate_date=DAY, rate_uah=Decimal("40"))

    body = api.get(f"/api/products/{product.id}/prices/?currency=UAH").json()
    pairs = {r["shop_name"]: r["price"] for r in body["results"]}
    assert pairs == {"A-shop": "2000.00", "B-shop": "2400.00"}
    assert body["currency"] == "UAH"


# --- «Отобразить историю цен»: по магазинам + средняя, курс СВОЕЙ даты --------

def test_history_converts_each_point_at_its_own_date_rate(api, offer):
    """Цена в USD постоянна, но курс растёт по дням → цена в UAH растёт.
    Каждая точка конвертируется курсом своей даты (исторический курс)."""
    d1, d2 = dt.date(2026, 6, 1), dt.date(2026, 6, 2)
    CurrencyRate.objects.create(code="USD", rate_date=d1, rate_uah=Decimal("40"))
    CurrencyRate.objects.create(code="USD", rate_date=d2, rate_uah=Decimal("50"))
    record_price(offer, Decimal("10"), d1)
    record_price(offer, Decimal("10"), d2)
    recompute_daily_stats(d1)
    recompute_daily_stats(d2)

    body = api.get(f"/api/products/{offer.product_id}/history/?currency=UAH").json()
    by_date = {p["date"]: p["price"] for p in body["shops"]["s1"]}
    assert by_date["2026-06-01"] == "400.00"   # 10 * 40
    assert by_date["2026-06-02"] == "500.00"   # 10 * 50 (курс той даты!)


def test_prices_and_history_404_on_unknown_product(api):
    """Несуществующий товар → 404 на всех его страницах (согласованно с detail)."""
    assert api.get("/api/products/999999/prices/").status_code == 404
    assert api.get("/api/products/999999/history/").status_code == 404


def test_history_includes_average_series(api, offer):
    """На графике, кроме магазинов, есть серия средней цены (тоже по курсу дня)."""
    CurrencyRate.objects.create(code="USD", rate_date=DAY, rate_uah=Decimal("40"))
    record_price(offer, Decimal("10"), DAY)
    recompute_daily_stats(DAY)
    body = api.get(f"/api/products/{offer.product_id}/history/?currency=UAH").json()
    avg = {p["date"]: p["price"] for p in body["average"]}
    assert avg["2026-06-01"] == "400.00"


# --- watchlist: пользователь ведёт свой список отслеживаемых товаров ----------

def test_watchlist_requires_auth(api, product):
    assert api.get("/api/watchlist/").status_code in (401, 403)


def test_watchlist_create_list_and_delete(auth_api, product):
    created = auth_api.post("/api/watchlist/", {"product": product.id})
    assert created.status_code == 201
    wid = created.json()["id"]
    assert len(auth_api.get("/api/watchlist/").json()["results"]) == 1
    assert auth_api.delete(f"/api/watchlist/{wid}/").status_code == 204
    assert auth_api.get("/api/watchlist/").json()["results"] == []


def test_watchlist_rejects_duplicate_with_400_not_500(auth_api, product):
    auth_api.post("/api/watchlist/", {"product": product.id})
    dup = auth_api.post("/api/watchlist/", {"product": product.id})
    assert dup.status_code == 400


def test_only_tracked_filter_limits_list_to_users_watchlist(auth_api, user, catalog):
    TrackedProduct.objects.create(user=user, product=catalog["cheap"])
    tracked = auth_api.get("/api/products/?only_tracked=true&ordering=price").json()
    assert [r["name"] for r in tracked["results"]] == ["Cheap"]
    full = auth_api.get("/api/products/?ordering=price").json()
    assert [r["name"] for r in full["results"]] == ["Cheap", "Mid", "Pricey"]


# --- алерты: привязка к пользователю -----------------------------------------

def test_alert_create_requires_auth(api, product):
    r = api.post(f"/api/products/{product.id}/alerts/", {"target_price": "5", "currency": "USD"})
    assert r.status_code in (401, 403)


def test_alert_is_scoped_to_its_owner(auth_api, api, product, django_user_model):
    auth_api.post(f"/api/products/{product.id}/alerts/", {"target_price": "5", "currency": "USD"})
    assert len(auth_api.get("/api/alerts/").json()["results"]) == 1
    other = django_user_model.objects.create_user(email="o@e.com", password="x12345678")
    api.force_authenticate(other)
    assert api.get("/api/alerts/").json()["results"] == []


def test_cannot_delete_foreign_alert(auth_api, api, product, django_user_model):
    auth_api.post(f"/api/products/{product.id}/alerts/", {"target_price": "5", "currency": "USD"})
    alert_id = auth_api.get("/api/alerts/").json()["results"][0]["id"]
    other = django_user_model.objects.create_user(email="o2@e.com", password="x12345678")
    api.force_authenticate(other)
    assert api.delete(f"/api/alerts/{alert_id}/").status_code == 404
