"""HOS-compliant trip planner.

Pure-Python module — no Django imports — so it can be unit-tested in isolation
and ported to a worker if we ever need to.

Implements the property-carrying driver rules from 49 CFR 395:

  * 11-hour driving limit within
  * 14-hour on-duty window after
  * 10 consecutive hours off-duty
  * 30-minute break required after 8 cumulative hours of driving
  * 70 hr / 8 day rolling cap (seeded from `current_cycle_used_hrs`)

Plus the brief's operating assumptions:

  * 1 hour on-duty for pickup, 1 hour on-duty for dropoff
  * Fuel stop (15 min on-duty) at least every 1,000 miles
  * No adverse-driving exception
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

# --- Rule constants (minutes, miles) ---------------------------------------

DRIVE_LIMIT_MIN = 11 * 60      # 660
WINDOW_LIMIT_MIN = 14 * 60     # 840
BREAK_AFTER_DRIVE_MIN = 8 * 60  # 480
CYCLE_LIMIT_MIN = 70 * 60      # 4200
OFF_DUTY_RESET_MIN = 10 * 60   # 600
BREAK_DURATION_MIN = 30
PICKUP_DROPOFF_MIN = 60
FUEL_DURATION_MIN = 15
FUEL_INTERVAL_MILES = 1000.0
DEFAULT_START_MINUTE = 8 * 60   # 08:00 of day 0


# --- Output dataclasses ----------------------------------------------------


@dataclass
class StopOut:
    sequence: int
    kind: str
    location_label: str
    arrive_minute: int
    depart_minute: int
    miles_from_start: float


@dataclass
class SegmentOut:
    day_index: int
    status: str         # off | sleeper | driving | on_duty
    start_minute: int   # 0..1440 within the day
    end_minute: int     # 0..1440 within the day
    remark: str = ""


@dataclass
class PlanResult:
    stops: list[StopOut] = field(default_factory=list)
    segments: list[SegmentOut] = field(default_factory=list)
    avg_mph: float = 0.0
    cycle_exceeded: bool = False
    summary_note: str = ""
    total_minutes: int = 0


# --- Internal helpers ------------------------------------------------------


def _emit_segment(
    raw: list[tuple[int, int, str, str]],
    start: int,
    duration: int,
    status: str,
    remark: str = "",
) -> int:
    """Append a duty segment in absolute minutes-from-trip-start."""
    if duration <= 0:
        return start
    raw.append((start, start + duration, status, remark))
    return start + duration


def _split_segments_into_days(
    raw: list[tuple[int, int, str, str]],
    trip_start_minute: int,
) -> list[SegmentOut]:
    """Slice absolute-minute segments into 24-hour day buckets keyed by day_index.

    `trip_start_minute` is the wall-clock minute the trip starts on day 0
    (e.g. 480 for 08:00). Day boundaries are at midnight wall-clock.
    """
    out: list[SegmentOut] = []
    for start_abs, end_abs, status, remark in raw:
        wall_start = trip_start_minute + start_abs
        wall_end = trip_start_minute + end_abs
        cur = wall_start
        while cur < wall_end:
            day_index = cur // 1440
            day_floor = day_index * 1440
            day_ceil = day_floor + 1440
            seg_end = min(wall_end, day_ceil)
            out.append(
                SegmentOut(
                    day_index=day_index,
                    status=status,
                    start_minute=cur - day_floor,
                    end_minute=seg_end - day_floor,
                    remark=remark,
                )
            )
            cur = seg_end
    return out


def _fill_off_duty_gaps(
    segs: list[SegmentOut],
    total_days: int,
) -> list[SegmentOut]:
    """Ensure every minute of every day is covered. Gaps become off-duty."""
    out: list[SegmentOut] = []
    for day in range(total_days):
        day_segs = sorted(
            (s for s in segs if s.day_index == day),
            key=lambda s: s.start_minute,
        )
        cursor = 0
        for s in day_segs:
            if s.start_minute > cursor:
                out.append(SegmentOut(day, "off", cursor, s.start_minute, ""))
            out.append(s)
            cursor = max(cursor, s.end_minute)
        if cursor < 1440:
            out.append(SegmentOut(day, "off", cursor, 1440, ""))
    return out


# --- Public API ------------------------------------------------------------


def plan_trip(
    *,
    current_cycle_used_hrs: float,
    total_distance_miles: float,
    total_drive_minutes: int,
    pickup_label: str = "Pickup",
    dropoff_label: str = "Dropoff",
    start_minute_of_day: int = DEFAULT_START_MINUTE,
) -> PlanResult:
    """Simulate a HOS-compliant trip schedule.

    All time math runs in *minutes from trip start*; we slice into wall-clock
    days at the very end.
    """
    result = PlanResult()

    if total_drive_minutes <= 0 or total_distance_miles <= 0:
        result.summary_note = "Pickup and dropoff must be different locations."
        return result

    avg_mph = total_distance_miles / (total_drive_minutes / 60.0)
    result.avg_mph = round(avg_mph, 2)
    miles_per_min = total_distance_miles / total_drive_minutes

    # State
    t = 0  # absolute minutes from trip start
    cycle_used = int(round(current_cycle_used_hrs * 60))
    drive_today = 0
    window_used = 0
    since_break = 0
    miles_driven = 0.0
    miles_since_fuel = 0.0
    drive_minutes_remaining = total_drive_minutes

    raw_segs: list[tuple[int, int, str, str]] = []
    stops: list[StopOut] = []
    seq = 0

    def push_stop(kind, label, arrive, depart, miles):
        nonlocal seq
        seq += 1
        stops.append(
            StopOut(
                sequence=seq,
                kind=kind,
                location_label=label,
                arrive_minute=arrive,
                depart_minute=depart,
                miles_from_start=round(miles, 1),
            )
        )

    # 1. Pickup (1 hour on-duty)
    push_stop("pickup", pickup_label, t, t + PICKUP_DROPOFF_MIN, 0.0)
    t = _emit_segment(raw_segs, t, PICKUP_DROPOFF_MIN, "on_duty", "Pickup")
    cycle_used += PICKUP_DROPOFF_MIN
    window_used += PICKUP_DROPOFF_MIN
    # since_break does NOT advance — only driving does

    # 2. Drive loop
    while drive_minutes_remaining > 0:
        # If we've blown the cycle cap, bail.
        if cycle_used >= CYCLE_LIMIT_MIN:
            result.cycle_exceeded = True
            result.summary_note = (
                "Trip cannot be completed within the remaining 70-hr/8-day cycle."
            )
            break

        candidates = [
            (DRIVE_LIMIT_MIN - drive_today, "rest"),
            (WINDOW_LIMIT_MIN - window_used, "rest"),
            (BREAK_AFTER_DRIVE_MIN - since_break, "break"),
            (CYCLE_LIMIT_MIN - cycle_used, "cycle"),
            (drive_minutes_remaining, "done"),
        ]
        # minutes until next forced fuel stop
        miles_to_fuel = FUEL_INTERVAL_MILES - miles_since_fuel
        if miles_to_fuel <= 0:
            min_to_fuel = 0
        else:
            min_to_fuel = int(miles_to_fuel / miles_per_min)
        candidates.append((min_to_fuel, "fuel"))

        # Drive the smallest non-negative window
        positive = [(m, why) for m, why in candidates if m > 0]
        if not positive:
            # Edge: forced-event with zero remaining — skip directly to event
            chunk_min = 0
            why = min(candidates, key=lambda c: c[0])[1]
        else:
            chunk_min, why = min(positive, key=lambda c: c[0])

        if chunk_min > 0:
            t = _emit_segment(raw_segs, t, chunk_min, "driving")
            cycle_used += chunk_min
            drive_today += chunk_min
            window_used += chunk_min
            since_break += chunk_min
            miles_chunk = chunk_min * miles_per_min
            miles_driven += miles_chunk
            miles_since_fuel += miles_chunk
            drive_minutes_remaining -= chunk_min

        # If we've finished the route, we're done — never insert a forced
        # event after the last driving minute (e.g. don't bolt a 30-min break
        # onto a trip that ended exactly at the 8-hr mark).
        if drive_minutes_remaining <= 0:
            break

        # Handle the forcing event
        if why == "done":
            break
        if why == "break":
            push_stop("break30", _ordinal_break_label(stops),
                      t, t + BREAK_DURATION_MIN, miles_driven)
            t = _emit_segment(raw_segs, t, BREAK_DURATION_MIN, "off", "30-min break")
            window_used += BREAK_DURATION_MIN  # break is in the 14-hr window
            since_break = 0
        elif why == "fuel":
            push_stop("fuel", "Fuel stop", t, t + FUEL_DURATION_MIN, miles_driven)
            t = _emit_segment(raw_segs, t, FUEL_DURATION_MIN, "on_duty", "Fueling")
            cycle_used += FUEL_DURATION_MIN
            window_used += FUEL_DURATION_MIN
            miles_since_fuel = 0.0
        elif why in ("rest", "cycle"):
            push_stop("rest10", "10-hr rest", t, t + OFF_DUTY_RESET_MIN, miles_driven)
            t = _emit_segment(raw_segs, t, OFF_DUTY_RESET_MIN, "sleeper",
                              "10-hr off-duty reset")
            # Reset the daily clocks (cycle_used keeps accumulating across rests)
            drive_today = 0
            window_used = 0
            since_break = 0

    # 3. Dropoff (1 hour on-duty) — only if we actually reached it
    if not result.cycle_exceeded:
        push_stop("dropoff", dropoff_label, t,
                  t + PICKUP_DROPOFF_MIN, total_distance_miles)
        t = _emit_segment(raw_segs, t, PICKUP_DROPOFF_MIN, "on_duty", "Dropoff")

    result.total_minutes = t

    # 4. Slice into wall-clock days, fill gaps with off-duty
    day_segs = _split_segments_into_days(raw_segs, start_minute_of_day)
    if day_segs:
        last_day = max(s.day_index for s in day_segs)
    else:
        last_day = 0
    result.segments = _fill_off_duty_gaps(day_segs, last_day + 1)
    result.stops = stops

    if not result.summary_note:
        days = last_day + 1
        result.summary_note = (
            f"{days}-day trip, {round(total_distance_miles, 1)} mi, "
            f"~{round(total_drive_minutes / 60, 1)} hr driving."
        )
    return result


def _ordinal_break_label(stops: Iterable[StopOut]) -> str:
    n = sum(1 for s in stops if s.kind == "break30") + 1
    return f"30-min break #{n}"
