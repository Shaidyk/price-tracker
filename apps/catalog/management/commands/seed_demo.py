"""Наполнить БД демо-данными БЕЗ обращения к сети.

Создаёт магазины, товары с предложениями, синтетические курсы валют (USD/EUR) и
историю цен за ~35 дней, затем пересчитывает дневные агрегаты — чтобы список,
деталь, история и тренды были видны сразу (в т.ч. в CI без интернета).

external_id предложений совпадают с id реальных API (dummyjson/fakestore), поэтому
после seed можно догрузить живые цены командой `fetch_now`.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import Offer, Product, Shop
from apps.currency.models import CurrencyRate
from apps.pricing.services import recompute_daily_stats

HISTORY_DAYS = 35

# (название, описание, dummyjson_id, fakestore_id|None, базовая цена USD)
PRODUCTS = [
    ("Essence Mascara Lash Princess", "Тушь для ресниц", "1", "1", Decimal("9.99")),
    ("Eyeshadow Palette with Mirror", "Палетка теней", "2", None, Decimal("19.99")),
    ("Powder Canister", "Пудра", "3", "2", Decimal("14.99")),
    ("Red Lipstick", "Помада", "4", None, Decimal("12.49")),
    ("Fjallraven Backpack", "Рюкзак", "100", "3", Decimal("109.95")),
    ("Mens Casual T-Shirt", "Футболка", "101", "4", Decimal("22.30")),
    ("Gold Bracelet", "Браслет", "102", "5", Decimal("695.00")),
    ("Solid Gold Petite", "Микро-кольцо", "103", "6", Decimal("168.00")),
]


class Command(BaseCommand):
    help = "Наполнить БД демо-данными (оффлайн)."

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        dummyjson, _ = Shop.objects.get_or_create(
            code="dummyjson", defaults={"name": "DummyJSON Store"}
        )
        fakestore, _ = Shop.objects.get_or_create(
            code="fakestore", defaults={"name": "Fake Store"}
        )

        offers: list[tuple[Offer, Decimal]] = []
        for name, desc, dj_id, fs_id, base in PRODUCTS:
            product, _ = Product.objects.get_or_create(
                name=name, defaults={"description": desc}
            )
            o1, _ = Offer.objects.get_or_create(
                product=product, shop=dummyjson, defaults={"external_id": dj_id}
            )
            offers.append((o1, base))
            if fs_id:
                # тот же товар в другом магазине, цена слегка отличается
                o2, _ = Offer.objects.get_or_create(
                    product=product, shop=fakestore, defaults={"external_id": fs_id}
                )
                offers.append((o2, base * Decimal("1.05")))

        self._seed_currency_rates()
        self._seed_price_history(offers)
        self._seed_demo_user()
        self.stdout.write(self.style.SUCCESS("Демо-данные созданы."))

    def _seed_demo_user(self) -> None:
        """Демо-пользователь + watchlist из первых 3 товаров (чтобы only_tracked был виден)."""
        from apps.accounts.models import User
        from apps.catalog.models import TrackedProduct

        user, created = User.objects.get_or_create(email="demo@pricetracker.local")
        if created:
            user.set_password("demo12345")
            user.save()
        for product in Product.objects.all()[:3]:
            TrackedProduct.objects.get_or_create(user=user, product=product)
        self.stdout.write(
            "Демо-пользователь: demo@pricetracker.local / demo12345 (watchlist: 3 товара)"
        )

    def _seed_currency_rates(self) -> None:
        """Синтетические курсы НБУ (UAH за 1 единицу) с лёгким дрейфом по дням."""
        today = dt.date.today()
        for delta in range(HISTORY_DAYS + 1):
            day = today - dt.timedelta(days=delta)
            drift = Decimal(delta) * Decimal("0.01")
            CurrencyRate.objects.update_or_create(
                code="USD", rate_date=day,
                defaults={"rate_uah": Decimal("40.00") - drift},
            )
            CurrencyRate.objects.update_or_create(
                code="EUR", rate_date=day,
                defaults={"rate_uah": Decimal("43.50") - drift},
            )

    def _seed_price_history(self, offers: list[tuple[Offer, Decimal]]) -> None:
        """История цен за HISTORY_DAYS дней + пересчёт агрегатов по каждому дню.

        Цена слегка растёт к сегодняшнему дню → у товаров появляется тренд «рост».
        Агрегаты считаем по дням по возрастанию (тренд опирается на прошлые дни).
        """
        from apps.pricing.services import record_price

        today = dt.date.today()
        days = [today - dt.timedelta(days=d) for d in range(HISTORY_DAYS, -1, -1)]
        for day in days:
            idx = (today - day).days  # 35..0
            factor = Decimal("1") + (Decimal(HISTORY_DAYS - idx) * Decimal("0.002"))
            for offer, base in offers:
                record_price(offer, (base * factor).quantize(Decimal("0.000001")), day)
            recompute_daily_stats(day)
