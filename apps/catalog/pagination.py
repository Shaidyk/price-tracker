from __future__ import annotations

from rest_framework.pagination import CursorPagination


class ProductCursorPagination(CursorPagination):
    """Keyset-пагинация списка товаров: не деградирует на глубоких страницах.

    Сортировка берётся из query-параметра `ordering`; product_id — стабильный
    tie-breaker, чтобы строки с равной ценой/трендом не терялись между страницами.
    """

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100

    _ORDERINGS = {
        "price": ("min_price_usd", "product_id"),
        "-price": ("-min_price_usd", "product_id"),
        "trend": ("trend_rank", "product_id"),
        "-trend": ("-trend_rank", "product_id"),
    }

    def get_ordering(self, request, queryset, view):
        key = request.query_params.get("ordering", "price")
        return self._ORDERINGS.get(key, self._ORDERINGS["price"])
