"""Каталог: магазины, товары и предложения (товар в конкретном магазине).

Расширяемый список магазинов — Shop с флагом is_active. Товар может быть в части
магазинов или во всех — связь many-to-many через Offer. Offer.external_id хранит
id товара в API его магазина, так что id из разных источников совмещаются свободно.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Shop(models.Model):
    """Магазин-источник цен.

    `code` связывает строку БД с адаптером в реестре `apps.integrations.shops`.
    Технически «как ходить в API» знает адаптер, а «включён ли магазин» — этот
    флаг, без передеплоя.
    """

    code = models.SlugField(unique=True, help_text="Ключ адаптера в реестре, напр. 'dummyjson'")
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Product(models.Model):
    """Каноничный товар, цены которого отслеживаем.

    Имя/описание — наши (можно брать из любого API). Конкретные цены живут в
    предложениях (Offer) по магазинам.
    """

    name = models.CharField(max_length=300)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["name"])]

    def __str__(self) -> str:
        return self.name


class Offer(models.Model):
    """Предложение: конкретный товар в конкретном магазине.

    Один товар может иметь предложения в части магазинов или во всех.
    external_id — id товара во внешнем API этого магазина.
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="offers")
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="offers")
    external_id = models.CharField(max_length=100, help_text="id товара в API магазина")
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            # один товар представлен в магазине ровно одним предложением
            models.UniqueConstraint(
                fields=["shop", "external_id"], name="uniq_offer_shop_external"
            ),
            models.UniqueConstraint(
                fields=["product", "shop"], name="uniq_offer_product_shop"
            ),
        ]
        indexes = [
            # активные предложения магазина — частый запрос воркера сбора цен
            models.Index(
                fields=["shop"], condition=models.Q(is_active=True), name="idx_offer_active_shop"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product.name} @ {self.shop.code}#{self.external_id}"


class TrackedProduct(models.Model):
    """Список товаров, которые отслеживает пользователь (его watchlist)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tracked"
    )
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="trackers")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "product"], name="uniq_user_product")
        ]

    def __str__(self) -> str:
        return f"{self.user}: {self.product}"
