"""Цены: сырая история и денормализованный дневной агрегат.

Разделение продиктовано масштабом (миллионы товаров, годы истории):
- PriceRecord — сырьё, одна строка = цена в магазине за день. Растёт неограниченно,
  в списках напрямую НЕ участвует.
- ProductDailyStat — агрегат на товар-день (min/max/avg + тренд). Его читает API.
Все цены в USD (base currency).
"""

from __future__ import annotations

from django.db import models


class Trend(models.TextChoices):
    UP = "up", "Рост"
    DOWN = "down", "Падение"
    SAME = "same", "Без изменений"


class PriceRecord(models.Model):
    """Сырая цена конкретного предложения за конкретный день (в USD)."""

    offer = models.ForeignKey(
        "catalog.Offer", on_delete=models.CASCADE, related_name="price_records"
    )
    date = models.DateField()
    price_usd = models.DecimalField(max_digits=18, decimal_places=6)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["offer", "date"], name="uniq_price_offer_date"),
            models.CheckConstraint(
                check=models.Q(price_usd__gte=0), name="price_non_negative"
            ),
        ]
        indexes = [
            # история по магазину/предложению — для графика
            models.Index(fields=["offer", "-date"], name="idx_price_offer_date"),
        ]

    def __str__(self) -> str:
        return f"{self.offer_id} {self.date}: ${self.price_usd}"


class ProductDailyStat(models.Model):
    """Дневной агрегат по товару (в USD) — основа списков и детали.

    min/max/avg за день по всем активным предложениям товара. `trend` — рост/падение
    относительно средней за предыдущие TREND_WINDOW_DAYS дней (считается в USD).
    """

    product = models.ForeignKey(
        "catalog.Product", on_delete=models.CASCADE, related_name="daily_stats"
    )
    date = models.DateField()
    min_price_usd = models.DecimalField(max_digits=18, decimal_places=6)
    max_price_usd = models.DecimalField(max_digits=18, decimal_places=6)
    avg_price_usd = models.DecimalField(max_digits=18, decimal_places=6)
    trend = models.CharField(max_length=4, choices=Trend.choices, default=Trend.SAME)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["product", "date"], name="uniq_stat_product_date"),
        ]
        indexes = [
            # список на сегодня с сортировкой по цене
            models.Index(fields=["date", "min_price_usd"], name="idx_stat_date_minprice"),
            # список на сегодня с сортировкой по тренду
            models.Index(fields=["date", "trend"], name="idx_stat_date_trend"),
        ]

    def __str__(self) -> str:
        return f"{self.product_id} {self.date}: {self.min_price_usd}-{self.max_price_usd}"
