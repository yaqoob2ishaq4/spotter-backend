"""Render a filled FMCSA Driver's Daily Log PDF, one page per day.

Layout closely mirrors the supplied blank-paper-log.png: bold title block,
date row, From/To, mileage + carrier blocks, BLACK 24-hour header bar with
white hour numbers, 4-row duty grid with quarter-hour ticks, Total Hours
column on the right, Remarks zone with vertical extension lines from the
grid hour ticks, Shipping fields, and the 70-hr/8-day & 60-day/7-day Recap
box block at the bottom.
"""

from __future__ import annotations

import io
from collections import defaultdict
from datetime import date, timedelta

from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from .models import Trip


# --- Page geometry ---------------------------------------------------------

PAGE_W, PAGE_H = letter            # 612 x 792 pt
M = 30                             # outer margin

# header band (top of page)
TOP = PAGE_H - M                   # 762

# duty-status grid
GRID_LEFT = M + 96                 # leave room for status row labels
GRID_RIGHT = PAGE_W - M - 56       # leave room for "Total Hours" column
TOTAL_COL_W = 56
HEADER_BAR_H = 12                  # the black hour-numbers bar
ROW_H = 18
GRID_TOP_Y = 560                   # top of header bar
GRID_HEAD_BOT_Y = GRID_TOP_Y - HEADER_BAR_H   # 548
GRID_BOTTOM_Y = GRID_HEAD_BOT_Y - ROW_H * 4   # 476

# remarks zone (below grid)
REMARKS_TOP = GRID_BOTTOM_Y - 12
REMARKS_VERT_EXT = 60              # vertical lines extend this far below grid
REMARKS_BOTTOM = GRID_BOTTOM_Y - REMARKS_VERT_EXT - 24


# --- Status rows -----------------------------------------------------------

ROW_LABELS = [
    ("1. Off Duty", "off"),
    ("2. Sleeper Berth", "sleeper"),
    ("3. Driving", "driving"),
    ("4. On Duty (not driving)", "on_duty"),
]

STATUS_COLORS = {
    "off": HexColor("#475569"),
    "sleeper": HexColor("#4338ca"),
    "driving": HexColor("#15803d"),
    "on_duty": HexColor("#b45309"),
}


# --- Helpers ---------------------------------------------------------------


def _fmt_hm(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    return f"{h}:{m:02d}"


def _x_for_minute(minute: int) -> float:
    frac = minute / 1440.0
    return GRID_LEFT + frac * (GRID_RIGHT - GRID_LEFT)


def _row_y_top(status: str) -> float:
    """Y of the top edge of a row."""
    for i, (_label, key) in enumerate(ROW_LABELS):
        if key == status:
            return GRID_HEAD_BOT_Y - ROW_H * i
    return GRID_HEAD_BOT_Y


def _row_y_center(status: str) -> float:
    return _row_y_top(status) - ROW_H / 2


# --- Top header block ------------------------------------------------------


def _draw_top(c: canvas.Canvas, trip: Trip, day_index: int, total_days: int):
    # Title
    c.setFont("Helvetica-Bold", 18)
    c.drawString(M, TOP - 14, "Driver's Daily Log")
    c.setFont("Helvetica", 8)
    c.drawString(M, TOP - 24, "(24 hours)")

    # Date — placed well to the right of the title
    today = date.today() + timedelta(days=day_index)
    cx = M + 230
    c.setFont("Helvetica", 11)
    c.drawString(cx, TOP - 14,
                 f"{today.month:02d}  /   {today.day:02d}   /   {today.year}")
    c.setFont("Helvetica", 7)
    c.drawString(cx + 4, TOP - 24, "(month)        (day)         (year)")

    # Top-right notes
    c.setFont("Helvetica", 8)
    c.drawRightString(PAGE_W - M, TOP - 8, "Original — File at home terminal.")
    c.drawRightString(
        PAGE_W - M, TOP - 19,
        "Duplicate — Driver retains in his/her possession for 8 days.",
    )
    c.setFont("Helvetica-Bold", 8)
    c.drawRightString(PAGE_W - M, TOP - 32,
                      f"Day {day_index + 1} of {total_days}")

    # From / To
    y = TOP - 48
    c.setFont("Helvetica-Bold", 10)
    c.drawString(M, y, "From:")
    c.setLineWidth(0.6)
    c.line(M + 32, y - 2, M + 250, y - 2)
    c.setFont("Helvetica", 9)
    c.drawString(M + 36, y, trip.pickup_location[:38])

    c.setFont("Helvetica-Bold", 10)
    c.drawString(M + 270, y, "To:")
    c.line(M + 290, y - 2, PAGE_W - M, y - 2)
    c.setFont("Helvetica", 9)
    c.drawString(M + 294, y, trip.dropoff_location[:42])

    # Mileage boxes (left) + carrier lines (right)
    y_box_top = y - 12
    box_w, box_h = 130, 30
    c.setLineWidth(0.7)
    c.rect(M, y_box_top - box_h, box_w, box_h)
    c.rect(M + box_w + 6, y_box_top - box_h, box_w, box_h)
    c.setFont("Helvetica", 7)
    c.drawString(M + 4, y_box_top - box_h - 9, "Total Miles Driving Today")
    c.drawString(M + box_w + 10, y_box_top - box_h - 9, "Total Mileage Today")

    # Optional total-miles fill (only on day 0; the breakdown by day is
    # not tracked in the Trip model, so we just show grand totals).
    if day_index == 0:
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(M + box_w / 2, y_box_top - box_h / 2 - 2,
                            f"{int(trip.total_distance_miles)}")
        c.drawCentredString(M + box_w + 6 + box_w / 2,
                            y_box_top - box_h / 2 - 2,
                            f"{int(trip.total_distance_miles)}")

    # right-side carrier/address lines
    rx = M + 2 * (box_w + 6) + 8
    rw = PAGE_W - M - rx
    c.setFont("Helvetica", 7)
    c.line(rx, y_box_top - 8, rx + rw, y_box_top - 8)
    c.drawString(rx, y_box_top - 16, "Name of Carrier or Carriers")
    c.line(rx, y_box_top - 20, rx + rw, y_box_top - 20)
    c.drawString(rx, y_box_top - 28, "Main Office Address")
    c.line(rx, y_box_top - 32, rx + rw, y_box_top - 32)
    c.drawString(rx, y_box_top - 40, "Home Terminal Address")

    # Truck/Trailer line under the mileage boxes
    y_truck = y_box_top - box_h - 14
    c.setFont("Helvetica", 7)
    c.line(M, y_truck, M + 2 * (box_w + 6) - 6, y_truck)
    c.drawString(M, y_truck - 8,
                 "Truck/Tractor and Trailer Numbers or License Plate(s)/State (show each unit)")


# --- 24-hour grid ----------------------------------------------------------


def _draw_grid(c: canvas.Canvas):
    grid_w = GRID_RIGHT - GRID_LEFT
    col_w = grid_w / 24.0

    # --- Black header bar with white hour numbers
    c.setFillColor(black)
    c.rect(GRID_LEFT, GRID_HEAD_BOT_Y, grid_w + TOTAL_COL_W, HEADER_BAR_H,
           stroke=0, fill=1)
    labels = ["Mid-\nnight", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
              "11", "Noon", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
              "11", "Mid-\nnight"]
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 6.5)
    for h, lab in enumerate(labels):
        x = GRID_LEFT + h * col_w
        if "\n" in lab:
            top, bot = lab.split("\n")
            c.drawCentredString(x, GRID_HEAD_BOT_Y + 6, top)
            c.drawCentredString(x, GRID_HEAD_BOT_Y + 1, bot)
        else:
            c.drawCentredString(x, GRID_HEAD_BOT_Y + 3, lab)

    # Total Hours label in header bar
    c.setFont("Helvetica-Bold", 7)
    c.drawCentredString(GRID_RIGHT + TOTAL_COL_W / 2,
                        GRID_HEAD_BOT_Y + 6, "Total")
    c.drawCentredString(GRID_RIGHT + TOTAL_COL_W / 2,
                        GRID_HEAD_BOT_Y + 1, "Hours")

    # --- Grid body
    c.setFillColor(black)
    c.setStrokeColor(black)
    c.setLineWidth(0.6)

    # outer rectangle (4 rows)
    c.rect(GRID_LEFT, GRID_BOTTOM_Y, grid_w, ROW_H * 4)
    # totals column
    c.rect(GRID_RIGHT, GRID_BOTTOM_Y, TOTAL_COL_W, ROW_H * 4)

    # row separators
    for i in range(1, 4):
        y = GRID_HEAD_BOT_Y - ROW_H * i
        c.line(GRID_LEFT, y, GRID_RIGHT + TOTAL_COL_W, y)

    # hour columns (heavy)
    c.setLineWidth(0.5)
    for h in range(25):
        x = GRID_LEFT + h * col_w
        c.line(x, GRID_BOTTOM_Y, x, GRID_HEAD_BOT_Y)

    # quarter-hour ticks per row (small marks at top + bottom of row, mid tick longer)
    c.setLineWidth(0.25)
    for h in range(24):
        x_left = GRID_LEFT + h * col_w
        for q in (1, 2, 3):
            qx = x_left + col_w * (q / 4.0)
            for r in range(4):
                ry_top = GRID_HEAD_BOT_Y - ROW_H * r
                ry_bot = ry_top - ROW_H
                tick = 4 if q == 2 else 2
                c.line(qx, ry_bot, qx, ry_bot + tick)
                c.line(qx, ry_top, qx, ry_top - tick)

    # status row labels (left side)
    c.setFont("Helvetica", 7.5)
    for i, (label, _) in enumerate(ROW_LABELS):
        y = GRID_HEAD_BOT_Y - ROW_H * (i + 0.5) - 2
        c.drawRightString(GRID_LEFT - 4, y, label)


def _draw_duty_line(c: canvas.Canvas, segments_for_day):
    if not segments_for_day:
        return
    segs = sorted(segments_for_day, key=lambda s: s.start_minute)
    c.setLineWidth(2.0)

    prev_y = None
    for seg in segs:
        y = _row_y_center(seg.status)
        x1 = _x_for_minute(seg.start_minute)
        x2 = _x_for_minute(seg.end_minute)
        c.setStrokeColor(STATUS_COLORS.get(seg.status, black))

        # vertical jump at the transition
        if prev_y is not None and abs(prev_y - y) > 0.5:
            c.line(x1, prev_y, x1, y)
        c.line(x1, y, x2, y)
        prev_y = y


def _draw_totals(c: canvas.Canvas, segments_for_day):
    totals = defaultdict(int)
    for s in segments_for_day:
        totals[s.status] += s.end_minute - s.start_minute
    grand = sum(totals.values())

    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 10)
    cx = GRID_RIGHT + TOTAL_COL_W / 2
    for i, (_label, key) in enumerate(ROW_LABELS):
        y = GRID_HEAD_BOT_Y - ROW_H * (i + 0.5) - 3
        c.drawCentredString(cx, y, _fmt_hm(totals.get(key, 0)))

    # grand total just under the totals column
    c.setFont("Helvetica", 7)
    c.drawCentredString(cx, GRID_BOTTOM_Y - 9,
                        f"Σ {_fmt_hm(grand)}")


# --- Remarks zone ----------------------------------------------------------


def _draw_remarks(c: canvas.Canvas, day_stops):
    grid_w = GRID_RIGHT - GRID_LEFT
    col_w = grid_w / 24.0

    # vertical extension lines from each hour tick into the remarks zone
    c.setStrokeColor(HexColor("#94a3b8"))
    c.setLineWidth(0.3)
    for h in range(25):
        x = GRID_LEFT + h * col_w
        c.line(x, GRID_BOTTOM_Y, x, GRID_BOTTOM_Y - REMARKS_VERT_EXT)
    # close the bottom of the extension band
    c.setLineWidth(0.5)
    c.setStrokeColor(black)
    c.line(GRID_LEFT, GRID_BOTTOM_Y - REMARKS_VERT_EXT,
           GRID_RIGHT, GRID_BOTTOM_Y - REMARKS_VERT_EXT)

    # "Remarks" label in left margin
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(M, GRID_BOTTOM_Y - 14, "Remarks")

    # mark each stop with a small tick + slanted text label, anchored at its
    # minute-of-day position
    if day_stops:
        c.setFont("Helvetica", 6.5)
        for s in day_stops:
            x = _x_for_minute(s["minute_of_day"])
            # short heavier tick from the bottom of the grid
            c.setStrokeColor(STATUS_COLORS.get("on_duty", black))
            c.setLineWidth(1.0)
            c.line(x, GRID_BOTTOM_Y, x, GRID_BOTTOM_Y - 6)
            # rotated label (so it fits between hour columns)
            c.saveState()
            c.translate(x + 1, GRID_BOTTOM_Y - 8)
            c.rotate(-60)
            c.setFillColor(black)
            label = f"{_fmt_hm(s['minute_of_day'])} {s['kind'].upper()} · {s['location_label'][:22]}"
            c.drawString(0, 0, label)
            c.restoreState()

    # Shipping doc fields under the extension band
    y = GRID_BOTTOM_Y - REMARKS_VERT_EXT - 16
    c.setFont("Helvetica-Bold", 8)
    c.drawString(M, y, "Shipping Documents:")
    c.setLineWidth(0.4)
    c.line(M + 110, y - 1, GRID_RIGHT, y - 1)

    y -= 14
    c.drawString(M, y, "DVL or Manifest No.:")
    c.line(M + 110, y - 1, GRID_RIGHT, y - 1)

    y -= 14
    c.drawString(M, y, "Shipper & Commodity:")
    c.line(M + 110, y - 1, GRID_RIGHT, y - 1)

    y -= 14
    c.setFont("Helvetica-Oblique", 7)
    c.drawCentredString(
        PAGE_W / 2, y,
        "Enter name of place you reported and where released from work, "
        "and when and where each change of duty occurred.",
    )
    y -= 9
    c.drawCentredString(PAGE_W / 2, y,
                        "Use time standard of home terminal.")

    return y - 8  # next y for the recap block


# --- Recap block -----------------------------------------------------------


def _draw_recap(c: canvas.Canvas, trip: Trip, top_y: float):
    # Layout: small "Recap" cell on the far left, two grouped sections —
    # 70 Hour / 8 Day Drivers (3 columns A/B/C) and 60 Day / 7 Day Drivers
    # (3 columns) — then a final "*If you took 34 consecutive hours off..." note.

    box_h = 78
    y_top = top_y
    y_bot = y_top - box_h
    if y_bot < M + 24:
        # Not enough room — clamp
        y_bot = M + 24
        box_h = y_top - y_bot

    c.setStrokeColor(black)
    c.setLineWidth(0.6)

    # left column: "Recap" + "Complete at end of day"
    rx0 = M
    rcol_w = 56
    c.rect(rx0, y_bot, rcol_w, box_h)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(rx0 + 4, y_top - 12, "Recap:")
    c.setFont("Helvetica", 6.5)
    _wrap(c, "Complete at end of day", rx0 + 4, y_top - 22, rcol_w - 8, 8)

    # On-duty hours today line (small text)
    c.setFont("Helvetica", 6.5)
    c.drawString(rx0 + 4, y_bot + 16, "On duty hours")
    c.drawString(rx0 + 4, y_bot + 8, "today, Total")
    c.drawString(rx0 + 4, y_bot, "lines 3 & 4")

    # 70 Hour / 8 Day Drivers — header strip + 3 boxes (A, B, C)
    sec1_x = rx0 + rcol_w + 4
    sec1_w = 200
    head_h = 14
    c.rect(sec1_x, y_bot, sec1_w, box_h)
    c.line(sec1_x, y_top - head_h, sec1_x + sec1_w, y_top - head_h)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(sec1_x + sec1_w / 2, y_top - 10, "70 Hour / 8 Day Drivers")
    sub_w = sec1_w / 3
    for i in range(1, 3):
        c.line(sec1_x + sub_w * i, y_bot, sec1_x + sub_w * i, y_top - head_h)
    c.setFont("Helvetica-Bold", 7)
    for i, lab in enumerate(["A.", "B.", "C."]):
        c.drawString(sec1_x + sub_w * i + 4, y_top - head_h - 9, lab)
    c.setFont("Helvetica", 6.2)
    descs1 = [
        "Total hours on\nduty last 7 days\nincluding today.",
        "Total hours\navailable\ntomorrow\n70 hr. minus A*.",
        "Total hours on\nduty last 5 days\nincluding today.",
    ]
    for i, d in enumerate(descs1):
        _wrap(c, d, sec1_x + sub_w * i + 4,
              y_top - head_h - 18, sub_w - 6, 7.5)

    # 60 Day / 7 Day Drivers — symmetric
    sec2_x = sec1_x + sec1_w + 4
    sec2_w = 200
    c.rect(sec2_x, y_bot, sec2_w, box_h)
    c.line(sec2_x, y_top - head_h, sec2_x + sec2_w, y_top - head_h)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(sec2_x + sec2_w / 2, y_top - 10, "60 Day / 7 Day Drivers")
    for i in range(1, 3):
        c.line(sec2_x + sub_w * i, y_bot, sec2_x + sub_w * i, y_top - head_h)
    c.setFont("Helvetica-Bold", 7)
    for i, lab in enumerate(["A.", "B.", "C."]):
        c.drawString(sec2_x + sub_w * i + 4, y_top - head_h - 9, lab)
    c.setFont("Helvetica", 6.2)
    descs2 = [
        "Total hours on\nduty last 8 days\nincluding today.",
        "Total hours\navailable\ntomorrow\n60 hr. minus A*.",
        "Total hours on\nduty last 7 days\nincluding today.",
    ]
    for i, d in enumerate(descs2):
        _wrap(c, d, sec2_x + sub_w * i + 4,
              y_top - head_h - 18, sub_w - 6, 7.5)

    # right-side asterisk note
    note_x = sec2_x + sec2_w + 4
    note_w = PAGE_W - M - note_x
    if note_w > 30:
        c.setFont("Helvetica", 6.5)
        c.rect(note_x, y_bot, note_w, box_h, stroke=1, fill=0)
        c.setFont("Helvetica-Bold", 6.5)
        c.drawString(note_x + 4, y_top - 10, "*If you took")
        c.setFont("Helvetica", 6.5)
        _wrap(c,
              "34 consecutive\nhours off duty\nyou have 60/70\nhours\navailable",
              note_x + 4, y_top - 19, note_w - 6, 7.8)

    # Trip summary line below recap (replaces the old summary that overlapped)
    y_summary = y_bot - 12
    if y_summary > M + 6:
        c.setFont("Helvetica", 7)
        msg = (f"Trip plan: {trip.summary_note}    "
               f"Cycle hours used at start of trip: "
               f"{trip.current_cycle_used_hrs:.1f} hr    "
               f"Distance: {int(trip.total_distance_miles)} mi @ ~{int(trip.avg_mph)} mph")
        c.drawString(M, y_summary, msg)
        if trip.cycle_exceeded:
            c.setFillColor(HexColor("#dc2626"))
            c.drawString(M, y_summary - 9,
                         "WARNING: trip exceeds remaining 70-hr / 8-day cycle.")
            c.setFillColor(black)


def _wrap(c: canvas.Canvas, text: str, x: float, y: float,
          max_w: float, line_h: float):
    """Tiny line-by-line writer for newline-delimited text (no smart wrap)."""
    for line in text.split("\n"):
        c.drawString(x, y, line)
        y -= line_h


# --- Public entry ----------------------------------------------------------


def build_log_pdf(trip: Trip) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)

    segs_by_day = defaultdict(list)
    for s in trip.segments.all():
        segs_by_day[s.day_index].append(s)
    days = sorted(segs_by_day.keys()) or [0]
    total_days = len(days)

    # Group stops by day for remarks (start of trip is 08:00 day 0)
    TRIP_START_MIN = 8 * 60
    stops_by_day: dict[int, list[dict]] = defaultdict(list)
    for st in trip.stops.all():
        wall = TRIP_START_MIN + st.arrive_minute
        d = wall // 1440
        mod = wall - d * 1440
        stops_by_day[d].append({
            "kind": st.kind,
            "location_label": st.location_label,
            "miles_from_start": st.miles_from_start,
            "minute_of_day": mod,
        })

    for day_index in days:
        _draw_top(c, trip, day_index, total_days)
        _draw_grid(c)
        _draw_duty_line(c, segs_by_day[day_index])
        _draw_totals(c, segs_by_day[day_index])
        next_y = _draw_remarks(c, stops_by_day.get(day_index, []))
        _draw_recap(c, trip, top_y=next_y)
        c.showPage()

    c.save()
    return buf.getvalue()
