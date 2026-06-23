"""API алертов: создать (на товаре), список своих, удалить.

Пользователь видит и трогает ТОЛЬКО свои алерты — queryset фильтруется по request.user.
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions
from rest_framework.serializers import BaseSerializer

from apps.catalog.models import Product

from .models import PriceAlert
from .serializers import PriceAlertSerializer


class AlertCreateView(generics.CreateAPIView):
    """POST /api/products/{product_id}/alerts/ {target_price, currency}"""

    serializer_class = PriceAlertSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer: BaseSerializer) -> None:
        product = get_object_or_404(Product, pk=self.kwargs["product_id"])
        serializer.save(user=self.request.user, product=product)


class AlertListView(generics.ListAPIView):
    """GET /api/alerts/ — алерты текущего пользователя."""

    serializer_class = PriceAlertSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return PriceAlert.objects.filter(user=self.request.user).order_by("-created_at")


class AlertDeleteView(generics.DestroyAPIView):
    """DELETE /api/alerts/{id}/ — только свой алерт."""

    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return PriceAlert.objects.filter(user=self.request.user)
