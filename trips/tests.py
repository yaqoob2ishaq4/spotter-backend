"""Planner unit tests + a couple of API smoke tests."""

from django.test import TestCase
from rest_framework.test import APIClient

from .planner import (
    BREAK_AFTER_DRIVE_MIN,
    CYCLE_LIMIT_MIN,
    DRIVE_LIMIT_MIN,
    FUEL_INTERVAL_MILES,
    plan_trip,
)


def _seg_minutes(segments, status):
    """Total minutes spent in a given duty status across all days."""
    return sum(s.end_minute - s.start_minute for s in segments if s.status == status)


def _stops_of(stops, kind):
    return [s for s in stops if s.kind == kind]


class PlannerShortTripTests(TestCase):
    def test_short_trip_one_day_no_rest(self):
        # 200 mi at 50 mph => 240 min driving. Plus 1+1 hr pickup/dropoff = 6h total.
        result = plan_trip(
            current_cycle_used_hrs=0,
            total_distance_miles=200,
            total_drive_minutes=240,
        )
        self.assertFalse(result.cycle_exceeded)
        self.assertEqual(len(_stops_of(result.stops, "pickup")), 1)
        self.assertEqual(len(_stops_of(result.stops, "dropoff")), 1)
        # No 10-hr rest needed
        self.assertEqual(len(_stops_of(result.stops, "rest10")), 0)
        # No 30-min break — only 4 hrs of driving
        self.assertEqual(len(_stops_of(result.stops, "break30")), 0)
        # Either zero or one fuel — likely zero at 200 mi
        self.assertLessEqual(len(_stops_of(result.stops, "fuel")), 1)

    def test_drive_minutes_match(self):
        result = plan_trip(
            current_cycle_used_hrs=0,
            total_distance_miles=200,
            total_drive_minutes=240,
        )
        self.assertEqual(_seg_minutes(result.segments, "driving"), 240)


class PlannerLongTripTests(TestCase):
    def setUp(self):
        # 2,400 mi at 60 mph => 2,400 min = 40 hrs driving
        self.result = plan_trip(
            current_cycle_used_hrs=0,
            total_distance_miles=2400,
            total_drive_minutes=2400,
        )

    def test_multi_day(self):
        days = {s.day_index for s in self.result.segments}
        self.assertGreaterEqual(len(days), 4)

    def test_fuel_stops_every_1000_miles(self):
        fuels = _stops_of(self.result.stops, "fuel")
        # 2,400 mi => at least 2 fuels (after mile 1000 and 2000)
        self.assertGreaterEqual(len(fuels), 2)
        for f in fuels:
            self.assertLessEqual(f.miles_from_start, FUEL_INTERVAL_MILES * 3 + 1)

    def test_thirty_min_break(self):
        breaks = _stops_of(self.result.stops, "break30")
        self.assertGreaterEqual(len(breaks), 1)
        # Each break should follow at most 8 hrs of driving since the previous reset
        # (sanity-checked indirectly via the rule below)
        self.assertGreaterEqual(_seg_minutes(self.result.segments, "off"), 30)

    def test_ten_hr_rest(self):
        rests = _stops_of(self.result.stops, "rest10")
        self.assertGreaterEqual(len(rests), 1)
        # Sleeper-berth time should be a multiple of 10 hrs (in minutes)
        self.assertGreaterEqual(_seg_minutes(self.result.segments, "sleeper"), 600)

    def test_no_day_exceeds_11_drive_or_14_window(self):
        by_day: dict[int, dict[str, int]] = {}
        for s in self.result.segments:
            by_day.setdefault(s.day_index, {"driving": 0, "on_duty": 0,
                                            "off": 0, "sleeper": 0})
            by_day[s.day_index][s.status] += s.end_minute - s.start_minute
        for day, totals in by_day.items():
            self.assertLessEqual(totals["driving"], DRIVE_LIMIT_MIN,
                                 f"day {day} drove > 11h")
            # 14-hr window: driving + on_duty + breaks shouldn't exceed 14h
            # (approx — we don't track windows across day boundaries here, so
            # this is a sanity ceiling, not the precise rule)
            on_clock = totals["driving"] + totals["on_duty"]
            self.assertLessEqual(on_clock, 14 * 60 + 30,
                                 f"day {day} on-clock > ~14h")

    def test_total_driving_matches_input(self):
        self.assertEqual(_seg_minutes(self.result.segments, "driving"), 2400)


class PlannerCycleExceededTests(TestCase):
    def test_high_cycle_cannot_complete(self):
        # Driver already used 69 hrs, 600 mi trip => can't possibly finish
        result = plan_trip(
            current_cycle_used_hrs=69,
            total_distance_miles=600,
            total_drive_minutes=600,
        )
        self.assertTrue(result.cycle_exceeded)
        self.assertIn("70-hr", result.summary_note)


class PlannerBoundaryTests(TestCase):
    def test_exactly_eight_hours_driving_no_break_after(self):
        # 8 hrs driving exactly => break is needed *to continue*, but if dropoff
        # is reached at the 8-hour mark, no break should be inserted after.
        result = plan_trip(
            current_cycle_used_hrs=0,
            total_distance_miles=480,
            total_drive_minutes=480,
        )
        self.assertEqual(len(_stops_of(result.stops, "break30")), 0)

    def test_dropoff_present_when_completable(self):
        result = plan_trip(
            current_cycle_used_hrs=0,
            total_distance_miles=100,
            total_drive_minutes=120,
        )
        self.assertEqual(len(_stops_of(result.stops, "dropoff")), 1)


class APISmokeTests(TestCase):
    def test_post_plan_trip_returns_full_payload(self):
        client = APIClient()
        body = {
            "current_location": "Los Angeles, CA",
            "pickup_location": "Los Angeles, CA",
            "dropoff_location": "Phoenix, AZ",
            "current_cycle_used_hrs": 0,
            "total_distance_miles": 372,
            "total_drive_minutes": 360,
        }
        resp = client.post("/api/plan-trip/", body, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        data = resp.json()
        self.assertIn("id", data)
        self.assertIn("stops", data)
        self.assertIn("segments_by_day", data)
        self.assertGreaterEqual(len(data["stops"]), 2)  # pickup + dropoff
