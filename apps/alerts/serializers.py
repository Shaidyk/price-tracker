from __future__ import annotations

from rest_framework import serializers

from apps.currency.services import supported_currencies

from .models import PriceAlert


class PriceAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceAlert
        fields = [
            "id",
            "product",
            "target_price",
            "currency",
            "is_active",
            "last_notified_date",
            "created_at",
        ]
        # product задаётся из URL (perform_create), не из тела запроса
        read_only_fields = ["id", "product", "is_active", "last_notified_date", "created_at"]

    def validate_target_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Цена должна быть больше нуля")
        return value

    def validate_currency(self, value: str) -> str:
        code = value.upper()
        if code not in supported_currencies():
            raise serializers.ValidationError(
                f"Валюта {code} не поддерживается (нет курсов). Доступны: "
                f"{', '.join(supported_currencies())}"
            )
        return code
