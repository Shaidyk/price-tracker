from __future__ import annotations

from django.urls import path

from . import views

urlpatterns = [
    path("products/", views.ProductListView.as_view(), name="product-list"),
    path("products/<int:pk>/", views.ProductDetailView.as_view(), name="product-detail"),
    path("products/<int:pk>/prices/", views.ProductPricesView.as_view(), name="product-prices"),
    path("products/<int:pk>/history/", views.ProductHistoryView.as_view(), name="product-history"),
    path("watchlist/", views.WatchlistView.as_view(), name="watchlist"),
    path("watchlist/<int:pk>/", views.WatchlistDeleteView.as_view(), name="watchlist-delete"),
]
