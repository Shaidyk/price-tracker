from __future__ import annotations

from django.contrib import admin

from .models import PriceAlert


@admin.register(PriceAlert)
class PriceAlertAdmin(admin.ModelAdmin):
    list_display = (
        "user", "product", "target_price", "currency", "is_active", "last_notified_date",
    )
    list_filter = ("is_active", "currency")
