from __future__ import annotations

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def healthcheck(_request) -> JsonResponse:
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", healthcheck, name="health"),
    path("api/", include("apps.catalog.urls")),
    path("api/", include("apps.alerts.urls")),
    # DRF login для браузерного API
    path("api-auth/", include("rest_framework.urls")),
]
