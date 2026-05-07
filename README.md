# Spotter ELD — Backend

Django + DRF service that turns trip details (current location, pickup, dropoff,
hours used) into:

1. A HOS-compliant **schedule** — pickup, fuel stops every 1,000 mi, mandatory
   30-min breaks, 10-hr off-duty resets, dropoff.
2. A **multi-page filled FMCSA Driver's Daily Log** PDF, one page per day.

The HOS rules engine ([`trips/planner.py`](trips/planner.py)) is a pure-Python
module with no Django imports, exhaustively tested in
[`trips/tests.py`](trips/tests.py). The PDF generator
([`trips/pdf.py`](trips/pdf.py)) draws a duty-status grid that mimics the
familiar paper log.

## API

| Method | Path                                      | Purpose |
| ------ | ----------------------------------------- | ------- |
| GET    | `/`                                       | health check (`{"status":"ok"}`) |
| POST   | `/api/plan-trip/`                         | run the HOS planner, persist the trip, return JSON |
| GET    | `/api/plan-trip/<uuid>/`                  | fetch a saved trip plan |
| GET    | `/api/plan-trip/<uuid>/logs.pdf`          | stream the multi-day filled log PDF |

### POST `/api/plan-trip/` body

```json
{
  "current_location": "Los Angeles, CA",
  "pickup_location":  "Los Angeles, CA",
  "pickup_lat":       34.0522,
  "pickup_lng":       -118.2437,
  "dropoff_location": "Chicago, IL",
  "dropoff_lat":      41.8781,
  "dropoff_lng":      -87.6298,
  "current_cycle_used_hrs": 10,
  "total_distance_miles":   2015,
  "total_drive_minutes":    1800
}
```

Distance + duration are computed **client-side** by the React frontend using
Mapbox Directions (so the backend has no outbound HTTP dependency — works on
PythonAnywhere's free tier without whitelist tweaks).

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # then edit values
python manage.py migrate
python manage.py runserver 8000
```

Run the tests:

```bash
python manage.py test trips
```

## Deploy to PythonAnywhere (free tier)

1. Push this repo to GitHub (e.g. `https://github.com/<you>/spotter-backend`).
2. Sign in to <https://www.pythonanywhere.com> and open a Bash console:
   ```bash
   git clone https://github.com/<you>/spotter-backend.git
   cd spotter-backend
   python3.11 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python manage.py migrate
   python manage.py collectstatic --noinput
   ```
3. Web tab → **Add a new web app** → Manual configuration → Python 3.11.
4. Edit the WSGI file (`/var/www/<user>_pythonanywhere_com_wsgi.py`):
   ```python
   import os, sys
   path = "/home/<user>/spotter-backend"
   if path not in sys.path:
       sys.path.insert(0, path)
   os.environ["DJANGO_SETTINGS_MODULE"] = "spotter_backend.settings"
   from django.core.wsgi import get_wsgi_application
   application = get_wsgi_application()
   ```
5. Set the **virtualenv** to `/home/<user>/spotter-backend/.venv`.
6. Add env vars in the same panel (or use an `.env` file alongside `manage.py`):
   - `DJANGO_DEBUG=False`
   - `DJANGO_SECRET_KEY=<run python -c "import secrets;print(secrets.token_urlsafe(50))">`
   - `DJANGO_ALLOWED_HOSTS=<user>.pythonanywhere.com`
   - `CORS_ALLOWED_ORIGINS=https://<your-vercel-app>.vercel.app`
7. Reload the web app. Verify: `curl https://<user>.pythonanywhere.com/`.

## Folder layout

```
spotter-backend/
├── spotter_backend/   # project settings, root urls, wsgi
└── trips/
    ├── models.py      # Trip, Stop, DutySegment
    ├── planner.py     # pure HOS rules engine
    ├── pdf.py         # ReportLab daily-log renderer
    ├── serializers.py # DRF I/O shapes
    ├── views.py       # plan-trip / logs.pdf endpoints
    └── tests.py       # 12 unit + smoke tests
```
