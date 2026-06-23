from __future__ import annotations

from django.urls import path

from . import views

urlpatterns = [
    path(
        "products/<int:product_id>/alerts/",
        views.AlertCreateView.as_view(),
        name="alert-create",
    ),
    path("alerts/", views.AlertListView.as_view(), name="alert-list"),
    path("alerts/<int:pk>/", views.AlertDeleteView.as_view(), name="alert-delete"),
]
