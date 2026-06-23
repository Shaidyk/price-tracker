from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.catalog.models import Offer, Product, Shop
from apps.currency.models import CurrencyRate


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(email="u@example.com", password="pass12345")


@pytest.fixture
def auth_api(api: APIClient, user) -> APIClient:
    api.force_authenticate(user=user)
    return api


@pytest.fixture
def shop():
    return Shop.objects.create(code="s1", name="Shop 1")


@pytest.fixture
def product():
    return Product.objects.create(name="Widget", description="desc")


@pytest.fixture
def offer(shop, product):
    return Offer.objects.create(product=product, shop=shop, external_id="1")


@pytest.fixture
def usd_rate():
    """Курс US=40 UAH на 2026-06-01."""
    return CurrencyRate.objects.create(
        code="USD", rate_date=dt.date(2026, 6, 1), rate_uah=Decimal("40")
    )
