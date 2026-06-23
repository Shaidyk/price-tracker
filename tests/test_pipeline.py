"""Связка Celery-пайплайна сбора цен (chord) — её не покрывал ни один тест.

Гоняем `fetch_all_prices` целиком в eager-режиме с in-memory backend (без Redis),
HTTP магазина замокан. Проверяем, что оркестровка реально доводит данные от
внешнего API до агрегатов и письма-алерта: fetch → record → recompute → alert.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import responses
from django.core import mail

from apps.alerts.models import PriceAlert
from apps.catalog.models import Offer, Product, Shop
from apps.currency.models import CurrencyRate
from apps.pricing.models import PriceRecord, ProductDailyStat
from apps.pricing.tasks import fetch_all_prices
from config.celery import app as celery_app

pytestmark = pytest.mark.django_db

DAY = dt.date(2026, 6, 1)


@pytest.fixture
def eager_celery():
    """Синхронное выполнение тасок и chord без брокера/Redis."""
    prev = dict(
        task_always_eager=celery_app.conf.task_always_eager,
        task_eager_propagates=celery_app.conf.task_eager_propagates,
        result_backend=celery_app.conf.result_backend,
    )
    celery_app.conf.task_always_eager = True
    # False: ретраи внутри таски должны отрабатывать штатно (исчерпание → return 0),
    # а не пробрасываться наружу — иначе chord не дойдёт до callback.
    celery_app.conf.task_eager_propagates = False
    celery_app.conf.result_backend = "cache+memory://"
    yield
    for k, v in prev.items():
        setattr(celery_app.conf, k, v)


@responses.activate
def test_full_pipeline_fetch_to_alert(eager_celery, django_user_model):
    responses.add(
        responses.GET, "https://dummyjson.com/products",
        json={"products": [{"id": 1, "title": "Phone", "description": "n", "price": 30}]},
        status=200,
    )
    shop = Shop.objects.create(code="dummyjson", name="DummyJSON")
    product = Product.objects.create(name="Phone")
    Offer.objects.create(product=product, shop=shop, external_id="1")
    CurrencyRate.objects.create(code="USD", rate_date=DAY, rate_uah=Decimal("40"))
    user = django_user_model.objects.create_user(email="u@e.com", password="x12345678")
    PriceAlert.objects.create(
        user=user, product=product, target_price=Decimal("50"), currency="USD"
    )

    fetch_all_prices.run(date_iso=DAY.isoformat())

    # 1) цена со внешнего API записана
    assert PriceRecord.objects.get(offer__product=product, date=DAY).price_usd == Decimal("30")
    # 2) агрегат пересчитан
    assert ProductDailyStat.objects.filter(product=product, date=DAY).exists()
    # 3) алерт сработал (30 < порога 50) — письмо ушло
    assert len(mail.outbox) == 1
    assert user.email in mail.outbox[0].to


@responses.activate
def test_pipeline_survives_one_shop_failing(eager_celery):
    """Падение одного магазина не должно сорвать сбор по остальным и пост-обработку."""
    responses.add(responses.GET, "https://dummyjson.com/products", status=500)
    responses.add(
        responses.GET, "https://fakestoreapi.com/products",
        json=[{"id": 9, "title": "Bag", "price": 12, "description": "d"}],
        status=200,
    )
    dummy = Shop.objects.create(code="dummyjson", name="Dummy")
    fake = Shop.objects.create(code="fakestore", name="Fake")
    product = Product.objects.create(name="Bag")
    Offer.objects.create(product=product, shop=dummy, external_id="1")  # упадёт
    Offer.objects.create(product=product, shop=fake, external_id="9")   # пройдёт

    fetch_all_prices.run(date_iso=DAY.isoformat())

    # данные рабочего магазина дошли до агрегата
    assert PriceRecord.objects.filter(offer__shop=fake, date=DAY).count() == 1
    assert ProductDailyStat.objects.filter(product=product, date=DAY).exists()


@responses.activate
def test_pipeline_survives_shop_without_adapter(eager_celery):
    """Магазин есть в БД, но адаптера в реестре нет (опечатка/не выкачен) — не рвём chord."""
    responses.add(
        responses.GET, "https://fakestoreapi.com/products",
        json=[{"id": 9, "title": "Bag", "price": 12, "description": "d"}],
        status=200,
    )
    ghost = Shop.objects.create(code="ghost", name="No adapter")  # нет в реестре
    fake = Shop.objects.create(code="fakestore", name="Fake")
    product = Product.objects.create(name="Bag")
    Offer.objects.create(product=product, shop=ghost, external_id="1")
    Offer.objects.create(product=product, shop=fake, external_id="9")

    fetch_all_prices.run(date_iso=DAY.isoformat())  # не должно бросить

    assert ProductDailyStat.objects.filter(product=product, date=DAY).exists()
