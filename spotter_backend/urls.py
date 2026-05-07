"""Root URL config — JSON API only, no admin in production paths."""

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    return JsonResponse({"status": "ok", "service": "spotter-backend"})


urlpatterns = [
    path("", health),
    path("admin/", admin.site.urls),
    path("api/", include("trips.urls")),
]
