"""Алерты «прислать email, если цена опустилась ниже указанной».

target_price задаётся в выбранной пользователем валюте (`currency`). Сравнение с
текущей ценой делаем в этой же валюте на дату снимка. `last_notified_date` защищает
от повторной отправки одного и того же письма каждый прогон.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class PriceAlert(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="alerts"
    )
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.CASCADE, related_name="alerts"
    )
    target_price = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    is_active = models.BooleanField(default=True)
    last_notified_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["is_active"], condition=models.Q(is_active=True), name="idx_alert_active"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user}: {self.product} < {self.target_price} {self.currency}"
