"""DRF-сериализаторы каталога.

Цены приходят из селекторов в USD; здесь приводим к выбранной валюте. Для списка
и детали множитель один на дату (передаётся в context), для истории — свой на каждую
дату (готовые числа уже подставлены во view).
"""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.currency.services import quantize_money

from .models import TrackedProduct


class ProductListSerializer(serializers.Serializer):
    """Элемент списка товаров. instance — ProductDailyStat."""

    id = serializers.IntegerField(source="product_id")
    name = serializers.CharField(source="product.name")
    price_from = serializers.SerializerMethodField()
    price_to = serializers.SerializerMethodField()
    trend = serializers.CharField()
    currency = serializers.SerializerMethodField()

    def _factor(self) -> Decimal:
        return self.context["factor"]

    def get_currency(self, _obj) -> str:
        return self.context["currency"]

    def get_price_from(self, obj) -> str:
        return str(quantize_money(obj.min_price_usd * self._factor()))

    def get_price_to(self, obj) -> str:
        return str(quantize_money(obj.max_price_usd * self._factor()))


class ProductDetailSerializer(serializers.Serializer):
    """Деталь товара. instance — ProductDailyStat (с product)."""

    id = serializers.IntegerField(source="product_id")
    name = serializers.CharField(source="product.name")
    description = serializers.CharField(source="product.description")
    price_from = serializers.SerializerMethodField()
    price_to = serializers.SerializerMethodField()
    trend = serializers.CharField()
    currency = serializers.SerializerMethodField()
    date = serializers.DateField()

    def get_currency(self, _obj) -> str:
        return self.context["currency"]

    def get_price_from(self, obj) -> str:
        return str(quantize_money(obj.min_price_usd * self.context["factor"]))

    def get_price_to(self, obj) -> str:
        return str(quantize_money(obj.max_price_usd * self.context["factor"]))


class TrackedProductSerializer(serializers.ModelSerializer):
    """Элемент watchlist. На вход принимает product (id), на выход — с именем товара."""

    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = TrackedProduct
        fields = ["id", "product", "product_name", "created_at"]
        read_only_fields = ["id", "product_name", "created_at"]

    def validate_product(self, product):
        # один товар в списке пользователя — один раз (иначе UniqueConstraint → 500)
        user = self.context["request"].user
        if TrackedProduct.objects.filter(user=user, product=product).exists():
            raise serializers.ValidationError("Товар уже в вашем списке")
        return product
