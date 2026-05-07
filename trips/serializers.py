"""DRF serializers for the public API."""

from rest_framework import serializers

from .models import DutySegment, Stop, Trip


class TripInputSerializer(serializers.Serializer):
    current_location = serializers.CharField(max_length=255)
    pickup_location = serializers.CharField(max_length=255)
    dropoff_location = serializers.CharField(max_length=255)
    current_cycle_used_hrs = serializers.FloatField(min_value=0, max_value=70)
    total_distance_miles = serializers.FloatField(min_value=0)
    total_drive_minutes = serializers.IntegerField(min_value=0)
    pickup_lat = serializers.FloatField(required=False, allow_null=True)
    pickup_lng = serializers.FloatField(required=False, allow_null=True)
    dropoff_lat = serializers.FloatField(required=False, allow_null=True)
    dropoff_lng = serializers.FloatField(required=False, allow_null=True)


class StopSerializer(serializers.ModelSerializer):
    class Meta:
        model = Stop
        fields = [
            "sequence",
            "kind",
            "location_label",
            "lat",
            "lng",
            "arrive_minute",
            "depart_minute",
            "miles_from_start",
        ]


class DutySegmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = DutySegment
        fields = ["day_index", "status", "start_minute", "end_minute", "remark"]


class TripSerializer(serializers.ModelSerializer):
    stops = StopSerializer(many=True, read_only=True)
    segments_by_day = serializers.SerializerMethodField()
    days = serializers.SerializerMethodField()

    class Meta:
        model = Trip
        fields = [
            "id",
            "current_location",
            "pickup_location",
            "dropoff_location",
            "current_cycle_used_hrs",
            "total_distance_miles",
            "total_drive_minutes",
            "avg_mph",
            "cycle_exceeded",
            "summary_note",
            "created_at",
            "stops",
            "segments_by_day",
            "days",
        ]

    def get_segments_by_day(self, obj):
        out: dict[int, list] = {}
        for seg in obj.segments.all():
            out.setdefault(seg.day_index, []).append(
                DutySegmentSerializer(seg).data
            )
        return out

    def get_days(self, obj):
        days = sorted({s.day_index for s in obj.segments.all()})
        return days
