"""HTTP views: plan a trip, fetch a saved trip, render the daily-log PDF."""

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.clickjacking import xframe_options_exempt
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import DutySegment, Stop, Trip
from .pdf import build_log_pdf
from .planner import plan_trip
from .serializers import TripInputSerializer, TripSerializer


@api_view(["POST"])
def plan_trip_view(request):
    """Run the planner over the supplied trip, persist it, and return the result."""
    payload = TripInputSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    data = payload.validated_data

    plan = plan_trip(
        current_cycle_used_hrs=data["current_cycle_used_hrs"],
        total_distance_miles=data["total_distance_miles"],
        total_drive_minutes=data["total_drive_minutes"],
        pickup_label=data["pickup_location"],
        dropoff_label=data["dropoff_location"],
    )

    trip = Trip.objects.create(
        current_location=data["current_location"],
        pickup_location=data["pickup_location"],
        dropoff_location=data["dropoff_location"],
        current_cycle_used_hrs=data["current_cycle_used_hrs"],
        total_distance_miles=data["total_distance_miles"],
        total_drive_minutes=data["total_drive_minutes"],
        avg_mph=plan.avg_mph,
        cycle_exceeded=plan.cycle_exceeded,
        summary_note=plan.summary_note,
    )

    pickup_lat = data.get("pickup_lat")
    pickup_lng = data.get("pickup_lng")
    dropoff_lat = data.get("dropoff_lat")
    dropoff_lng = data.get("dropoff_lng")

    Stop.objects.bulk_create([
        Stop(
            trip=trip,
            sequence=s.sequence,
            kind=s.kind,
            location_label=s.location_label,
            lat=pickup_lat if s.kind == "pickup" else
                dropoff_lat if s.kind == "dropoff" else None,
            lng=pickup_lng if s.kind == "pickup" else
                dropoff_lng if s.kind == "dropoff" else None,
            arrive_minute=s.arrive_minute,
            depart_minute=s.depart_minute,
            miles_from_start=s.miles_from_start,
        )
        for s in plan.stops
    ])

    DutySegment.objects.bulk_create([
        DutySegment(
            trip=trip,
            day_index=seg.day_index,
            status=seg.status,
            start_minute=seg.start_minute,
            end_minute=seg.end_minute,
            remark=seg.remark,
        )
        for seg in plan.segments
    ])

    serialized = TripSerializer(trip).data
    return Response(serialized, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def get_trip_view(request, trip_id):
    trip = get_object_or_404(Trip, pk=trip_id)
    return Response(TripSerializer(trip).data)


@xframe_options_exempt
def trip_log_pdf_view(request, trip_id):
    """Render and stream the multi-day filled log PDF.

    `xframe_options_exempt` removes the default X-Frame-Options: DENY header
    so the PDF can be embedded in the React frontend's <iframe> across origins.
    """
    try:
        trip = Trip.objects.get(pk=trip_id)
    except Trip.DoesNotExist as exc:
        raise Http404 from exc
    pdf_bytes = build_log_pdf(trip)
    resp = FileResponse(
        iter([pdf_bytes]),
        content_type="application/pdf",
    )
    resp["Content-Disposition"] = f'inline; filename="eld-logs-{trip.id}.pdf"'
    # Some browsers also enforce CSP frame-ancestors; explicitly allow all so
    # the iframe loads on Vercel + localhost without juggling per-environment
    # config. (The PDF endpoint is read-only and idempotent.)
    resp["Content-Security-Policy"] = "frame-ancestors *"
    return resp
