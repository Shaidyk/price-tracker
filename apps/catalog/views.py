"""API каталога: список, деталь, цены на сегодня, история цен.

Вьюхи тонкие: распарсить параметры → селектор → конвертация валют → ответ.
Параметр `currency` (по умолчанию USD) задаёт валюту отображения.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.currency.services import (
    RateUnavailable,
    conversion_factor,
    factors_for_dates,
    quantize_money,
)

from . import selectors
from .models import Product, TrackedProduct
from .pagination import ProductCursorPagination
from .serializers import (
    ProductDetailSerializer,
    ProductListSerializer,
    TrackedProductSerializer,
)


def _currency(request: Request) -> str:
    return request.query_params.get("currency", settings.BASE_CURRENCY).upper()


def _parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


class ProductListView(ListAPIView):
    """GET /api/products/?currency=&ordering=price|-price|trend|-trend&only_tracked=

    only_tracked=true ограничивает список watchlist'ом текущего пользователя.
    """

    serializer_class = ProductListSerializer
    pagination_class = ProductCursorPagination
    filter_backends: list = []  # сортировку/пагинацию ведёт keyset-пагинатор

    def get_queryset(self):
        only_tracked = self.request.query_params.get("only_tracked", "").lower() in {
            "1",
            "true",
            "yes",
        }
        product_ids = None
        if only_tracked:
            user = self.request.user
            product_ids = (
                selectors.watchlist_product_ids(user)
                if user.is_authenticated
                else set()  # аноним без списка → пусто
            )
        return selectors.products_for_list(product_ids)

    def list(self, request: Request, *args, **kwargs) -> Response:
        currency = _currency(request)
        on_date = selectors.latest_stat_date()
        if on_date is None:
            return Response({"results": []})
        try:
            factor = conversion_factor(currency, on_date)
        except RateUnavailable as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        ctx = {**self.get_serializer_context(), "currency": currency, "factor": factor}
        serializer = self.get_serializer(page, many=True, context=ctx)
        return self.get_paginated_response(serializer.data)


class ProductDetailView(APIView):
    """GET /api/products/{id}/?currency="""

    def get(self, request: Request, pk: int) -> Response:
        stat = selectors.latest_stat_for_product(pk)
        if stat is None:
            return Response({"detail": "Нет данных по товару"}, status=status.HTTP_404_NOT_FOUND)
        currency = _currency(request)
        try:
            factor = conversion_factor(currency, stat.date)
        except RateUnavailable as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        data = ProductDetailSerializer(stat, context={"currency": currency, "factor": factor}).data
        return Response(data)


class ProductPricesView(APIView):
    """GET /api/products/{id}/prices/?currency=  — пары «магазин-цена» на сегодня."""

    def get(self, request: Request, pk: int) -> Response:
        get_object_or_404(Product, pk=pk)
        on_date = selectors.latest_stat_date()
        if on_date is None:
            return Response({"results": []})
        currency = _currency(request)
        try:
            factor = conversion_factor(currency, on_date)
        except RateUnavailable as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        rows = selectors.today_prices_per_shop(pk, on_date)
        results = [
            {
                "shop_code": r["shop_code"],
                "shop_name": r["shop_name"],
                "price": str(quantize_money(r["price_usd"] * factor)),
                "currency": currency,
                "date": r["date"],
            }
            for r in rows
        ]
        return Response({"date": on_date, "currency": currency, "results": results})


class ProductHistoryView(APIView):
    """GET /api/products/{id}/history/?currency=&shop=&date_from=&date_to=

    КЛЮЧЕВОЙ эндпоинт: каждую точку конвертируем курсом ЕЁ даты (исторический курс).
    """

    def get(self, request: Request, pk: int) -> Response:
        get_object_or_404(Product, pk=pk)
        currency = _currency(request)
        shop = request.query_params.get("shop")
        date_from = _parse_date(request.query_params.get("date_from"))
        date_to = _parse_date(request.query_params.get("date_to"))
        # Без явного диапазона отдаём последнее окно, а не всю историю за годы.
        if date_from is None and date_to is None:
            date_from = timezone.localdate() - dt.timedelta(days=settings.HISTORY_DEFAULT_DAYS)

        history = selectors.price_history(pk, shop, date_from, date_to)

        # собрать все даты серии и посчитать множитель на каждую дату один раз
        all_dates = [d for series in history["shops"].values() for d, _ in series]
        all_dates += [d for d, _ in history["average"]]
        try:
            factors = factors_for_dates(currency, all_dates)
        except RateUnavailable as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        def to_currency(value: Decimal, day: dt.date) -> str:
            return str(quantize_money(value * factors[day]))

        shops = {
            code: [{"date": d, "price": to_currency(v, d)} for d, v in series]
            for code, series in history["shops"].items()
        }
        average = [{"date": d, "price": to_currency(v, d)} for d, v in history["average"]]
        return Response({"currency": currency, "shops": shops, "average": average})


class WatchlistView(generics.ListCreateAPIView):
    """GET/POST /api/watchlist/ — список отслеживаемых товаров пользователя.

    Способ для пользователя собрать свой список отслеживаемых товаров. Scoped по user.
    """

    serializer_class = TrackedProductSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            TrackedProduct.objects.filter(user=self.request.user)
            .select_related("product")
            .order_by("-created_at")
        )

    def perform_create(self, serializer) -> None:
        serializer.save(user=self.request.user)


class WatchlistDeleteView(generics.DestroyAPIView):
    """DELETE /api/watchlist/{id}/ — убрать товар из своего списка."""

    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return TrackedProduct.objects.filter(user=self.request.user)
