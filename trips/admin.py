from django.contrib import admin

from .models import DutySegment, Stop, Trip


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "pickup_location",
        "dropoff_location",
        "total_distance_miles",
        "cycle_exceeded",
        "created_at",
    )


@admin.register(Stop)
class StopAdmin(admin.ModelAdmin):
    list_display = ("trip", "sequence", "kind", "location_label", "miles_from_start")
    list_filter = ("kind",)


@admin.register(DutySegment)
class DutySegmentAdmin(admin.ModelAdmin):
    list_display = ("trip", "day_index", "status", "start_minute", "end_minute")
    list_filter = ("status", "day_index")
