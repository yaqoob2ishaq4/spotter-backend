from django.urls import path

from .views import get_trip_view, plan_trip_view, trip_log_pdf_view

urlpatterns = [
    path("plan-trip/", plan_trip_view, name="plan_trip"),
    path("plan-trip/<uuid:trip_id>/", get_trip_view, name="get_trip"),
    path("plan-trip/<uuid:trip_id>/logs.pdf", trip_log_pdf_view, name="trip_log_pdf"),
]
