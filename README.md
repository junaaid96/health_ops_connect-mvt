# HealthOPS Connect

**Hospital operations and patient care, connected.** Patients describe their symptoms, get matched to the
right specialist, book a real time slot, check in from their phone and wait wherever they like. Doctors
get a triage-ordered queue and a consultation workspace. Operations staff get a live command center.

Live: https://health-ops-connect-mvt.onrender.com

## What's inside

### For patients
- **Care finder** — describe symptoms in plain words; a transparent rule engine suggests the right
  specialty and shows *which words* led there. Red-flag phrases (chest pain, stroke signs, severe
  bleeding, self-harm…) trigger an emergency banner instead of a booking.
- **Live-availability booking** — weekly schedules become bookable slots; in-person or video visits.
  Double-booking is impossible (enforced by a partial unique index in Postgres, not just the view).
- **Digital intake** — reason, symptoms, severity and duration are captured while booking, with live
  triage hints; urgency is computed automatically.
- **Digital check-in & virtual queue** — check in from your phone up to 2 hours early, get a token and a
  live wait estimate learned from the doctor's *actual* recent consultation times. Priority follows
  clinical urgency, then arrival.
- **Smart waitlist** — join the waitlist for a fully booked day; you're notified the moment someone
  cancels or reschedules.
- **Video visits** — per-visit, unguessable Jitsi rooms (or the doctor's own meeting link).
- **Health passport & vitals** — allergies, conditions, medications, emergency contact; log BP, heart
  rate, glucose, SpO₂, temperature and weight with trend charts and range alerts.
- **Verifiable e-prescriptions** — printable prescriptions with a QR code pharmacies scan to confirm
  they're genuine (public verify page shows initials only).
- **Privacy log** — every clinician/staff access to your record is logged and visible to you.
- Calendar (.ics) export, reschedule/cancel, reviews after completed visits, in-app + email notifications.

### For doctors
- Today's schedule, live queue with one-click **Call next**, weekly stats and a 14-day trend.
- **Consultation workspace**: intake, allergy banner, vitals trends, previous visits side by side; write
  notes and prescriptions with an automatic **drug–allergy conflict check** (overrides are explicit
  and recorded).
- Weekly hours editor, time off, public profile editor. New doctors apply and are listed only after
  operations staff verify their licence.

### For operations staff
- **Command center**: visits today, waiting, urgent cases, revenue collected/outstanding, attendance,
  per-doctor utilisation and queue load, ward occupancy, 14-day outcome chart.
- **Front desk**: today's arrivals with check-in, payment, no-show and cancel actions.
- **Bed board**: ward/bed grid, admit & discharge (discharged beds go to *cleaning* first).
- **Waiting-room screen** (`/queue/`): a TV display that shows token numbers only — never names.

## Tech

- Django 5.2 (MVT), Python 3.11+
- **Neon serverless Postgres** (psycopg 3), SQLite fallback for local hacking
- Tailwind CSS v4 (compiled & committed — no Node needed to deploy), htmx for live partial updates,
  Alpine.js for small interactions, Chart.js for charts, Lucide icons (inlined server-side)
- WhiteNoise for static files, Gunicorn in production
- Accessible by design: semantic HTML, keyboard focus styles, skip link, status never shown by colour
  alone, chart data always available as a table, dark mode, reduced-motion support

## Project layout

```
accounts/      custom User (patient / doctor / staff roles), auth, notifications
clinic/        specialties, doctors, weekly availability, time off, reviews, care-finder triage engine
appointments/  booking, reschedule/cancel, check-in, queue & wait-time logic (services.py), waitlist, .ics
records/       health passport, vitals, consultations & prescriptions, QR verification, access log
operations/    command center, front desk, wards/beds/admissions, waiting-room display
core/          home & dashboards, template tags, icons, seed_demo command, tests
assets/        Tailwind source + vendoring script     static/  compiled CSS, vendored JS
```

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # set SECRET_KEY; leave DATABASE_URL unset for SQLite
python manage.py migrate
python manage.py seed_demo      # optional: a realistic demo hospital
python manage.py runserver
```

Demo accounts (password `HealthOps!2026`): `patient@demo.health`, `doctor@demo.health`,
`ops@demo.health`, `admin@demo.health` (superuser). Run `python manage.py seed_demo --today` any day
to regenerate a live queue for today.

Frontend (only when you change templates/CSS): `npm install && npm run build` (or `npm run watch:css`).

Tests: `python manage.py test`

## Database: Neon

The app reads `DATABASE_URL`. Use Neon's **pooled** connection string (host contains `-pooler`):

```
postgresql://USER:PASSWORD@ep-xxxx-pooler.<region>.aws.neon.tech/healthops?sslmode=require&channel_binding=require
```

Copy it from the Neon console → project **health-ops-connect** → *Connect*. Keep Render and Neon in the
same region (Neon project is in `aws-ap-southeast-1`, Singapore) for low latency.

## Deploy on Vercel

Live: https://health-ops-connect.vercel.app

Vercel detects Django (`manage.py` → `WSGI_APPLICATION`), installs `requirements.txt`, runs
`collectstatic` and serves static files from its CDN. `vercel.json` pins the function to `sin1`
(Singapore, next to the Neon database and bucket) and runs `vercel-build.sh`, which applies
migrations, makes sure the demo photos are in object storage and — with `SEED_DEMO=true` — loads the
demo hospital. Set the same environment variables as below plus `DB_CONN_MAX_AGE=0`.

## Deploy on Render

- **Build command:** `./build.sh`
- **Start command:** `gunicorn health_ops_connect.wsgi:application --workers 3 --timeout 60`
- **Environment:** `DATABASE_URL`, `SECRET_KEY`, `DEBUG=False`, `SITE_URL=https://<your-app>.onrender.com`,
  the `AWS_*` object-storage variables below, optionally `SEED_DEMO=true` (first deploy), `TIME_ZONE`,
  `CURRENCY_SYMBOL`, SMTP settings — see `.env.example`.

## File storage: Neon Object Storage

Uploads (doctor photos, avatars) go to the private bucket `healthops-media` on the Neon `main` branch
through `django-storages` (S3 API, path-style, SigV4). Files are served with signed URLs that expire
after an hour, so nothing in the bucket is publicly readable. Configure with:

```
AWS_STORAGE_BUCKET_NAME=healthops-media
AWS_ENDPOINT_URL_S3=<branch storage endpoint>     # Neon console → Connect → Storage
AWS_REGION=ap-southeast-1
AWS_ACCESS_KEY_ID=<credential token_id>           # a credential with storage:read + storage:write
AWS_SECRET_ACCESS_KEY=<credential s3_secret_access_key>
```

Buckets branch with the database: a Neon preview branch sees the same files copy-on-write, and
uploads there don't touch production. Without `AWS_STORAGE_BUCKET_NAME`, files stay on local disk.
`seed_demo --media` (run by `build.sh`) uploads the bundled demo doctor photos if they're missing.
