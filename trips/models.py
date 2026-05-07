"""Persistence for trip plans, stops, and ELD duty segments."""

import uuid

from django.db import models


class StopKind(models.TextChoices):
    START = "start", "Start"
    PICKUP = "pickup", "Pickup"
    FUEL = "fuel", "Fuel"
    BREAK30 = "break30", "30-min Break"
    REST10 = "rest10", "10-hr Rest"
    DROPOFF = "dropoff", "Dropoff"


class DutyStatus(models.TextChoices):
    OFF = "off", "Off Duty"
    SLEEPER = "sleeper", "Sleeper Berth"
    DRIVING = "driving", "Driving"
    ON_DUTY = "on_duty", "On Duty (not driving)"


class Trip(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    current_location = models.CharField(max_length=255)
    pickup_location = models.CharField(max_length=255)
    dropoff_location = models.CharField(max_length=255)
    current_cycle_used_hrs = models.FloatField()

    total_distance_miles = models.FloatField()
    total_drive_minutes = models.IntegerField()

    avg_mph = models.FloatField()
    cycle_exceeded = models.BooleanField(default=False)
    summary_note = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Stop(models.Model):
    trip = models.ForeignKey(Trip, related_name="stops", on_delete=models.CASCADE)
    sequence = models.IntegerField()
    kind = models.CharField(max_length=16, choices=StopKind.choices)
    location_label = models.CharField(max_length=255, blank=True, default="")
    lat = models.FloatField(null=True, blank=True)
    lng = models.FloatField(null=True, blank=True)
    arrive_minute = models.IntegerField()
    depart_minute = models.IntegerField()
    miles_from_start = models.FloatField()

    class Meta:
        ordering = ["sequence"]


class DutySegment(models.Model):
    trip = models.ForeignKey(Trip, related_name="segments", on_delete=models.CASCADE)
    day_index = models.IntegerField()
    status = models.CharField(max_length=16, choices=DutyStatus.choices)
    start_minute = models.IntegerField()
    end_minute = models.IntegerField()
    remark = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["day_index", "start_minute"]
