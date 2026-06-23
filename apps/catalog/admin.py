from __future__ import annotations

from django.contrib import admin

from .models import Offer, Product, Shop, TrackedProduct


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ("product", "shop", "external_id", "is_active")
    list_filter = ("shop", "is_active")


@admin.register(TrackedProduct)
class TrackedProductAdmin(admin.ModelAdmin):
    """Watchlist: здесь можно вручную добавить товар в список пользователя."""

    list_display = ("user", "product", "created_at")
    list_filter = ("user",)
