# QRotation — Deep Documentation

QRotation is a production-grade, privacy-first attendance platform built with Python and Flask. It provides secure, rotating QR-based attendance with real-time synchronization, explainable presence signals, fraud review workflows, and tools for professors, students, and administrators.

This README is a deep, developer-focused reference that documents architecture, data models, configuration options, the QR attendance flow, API contract, deployment recommendations, testing guidance, and extension points.

Table of contents
- Overview
- Architecture and key components
- Data model (summary)
- QR token & attendance flow (detailed)
- Security and privacy considerations
- Configuration (env vars and Config)
- Installation, development, and running
- Testing and validation
- API endpoints and contracts
- Templates, front-end notes, and PWA behavior
- Utilities and helper scripts
- Maintenance, scaling, and deployment
- Troubleshooting & FAQs
- Contributing

## Overview

QRotation centers on short-lived, server-issued QR tokens that rotate frequently to prevent replay or screenshot abuse. Professors create class sessions; the system generates QR tokens for active sessions, students scan these tokens to record attendance, and a multi-signal verification pipeline (device binding, IP, optional geofence/beacon, and token validity) produces explainable presence scores.

The codebase uses Flask for HTTP routes and Flask-SocketIO for real-time updates. SQLAlchemy models persist users, classes, sessions, QR tokens, attendance records, and audit artifacts.

Supported roles
- `student` — scans QR, views attendance history, manages devices
- `professor` — creates classes, starts/stops sessions, views realtime attendance and reports
- `admin` — institution-level configuration and audit

## Architecture and key components

- `app/` — application package
  - `__init__.py` — app factory, extension initialization (SQLAlchemy, LoginManager, SocketIO)
  - `models.py` — comprehensive SQLAlchemy data model (users, students, professors, courses, sessions, QR tokens, attendance records, fraud alerts, appeals, etc.)
  - `routes/` — Blueprints implementing `auth`, `main`, `student`, `professor`, `api`, `admin` endpoints
  - `templates/` — Jinja2 templates and Tailwind-based UI
  - `static/` — static assets, service worker and PWA manifest
  - `utils/` — helper modules: `qr_generator.py`, `session_generator.py`, `attendance_service.py`, `email_service.py`, `reports.py`, `session_roster.py`, `time_utils.py` and more

- Top-level
  - `config.py` — central configuration class (defaults + environment variables)
  - `.env` / `.env.example` — environment configuration guidance
  - `README.md` — this document

## Data model (summary)

The canonical models are implemented in `app/models.py`. Key tables:

- `User` — central auth user. Fields: `email`, `password_hash`, `role` (`student`, `professor`, `admin`), `first_name`, `last_name`, timestamps, profile relations.
- `Student` / `Professor` — role-specific profiles linked to `User`.
- `Course` / `Department` / `AcademicPeriod` — catalog and academic configuration.
- `ClassInstance` — a course offering in a term (section number, `class_code`, days, times, room, enrollment limits).
- `ClassSession` — a single meeting instance of a `ClassInstance`; holds QR token metadata, status (`scheduled`, `active`, `completed`), and attendance counters.
- `QRToken` — durable, short-lived tokens with `token_hash`, `expires_at`, `revoked_at` used to validate scans.
- `Enrollment` — student enrollment in a class instance.
- `SessionRoster` — snapshot of eligible students for a session.
- `AttendanceRecord` — attendance events recorded when a student scans; contains presence signals (device fingerprint, IP, geolocation) and verification fields.
- `PresenceVerification` — explainable verification result for an attendance event (booleans for `qr_verified`, `device_verified`, `location_verified`, `beacon_verified` and a `confidence_score`).
- `FraudAlert` / `AttendanceAppeal` — review flows and audit trails.

Refer to `app/models.py` for full field definitions and constraints (unique constraints for `attendance_records`, `enrollments`, etc.).

## QR token & attendance flow (detailed)

1. Professor starts a session via `/professor/sessions/<id>/activate`.
2. Server generates a new `ClassSession` record (if needed) and issues one or more `QRToken` entries tied to the session; tokens are HMAC-signed, include a `nonce`, `timestamp`, `sessionId`, and `expiresAt`.
3. The token content is presented as a QR code on the professor UI (rotates every `QR_ROTATION_INTERVAL` seconds). The backend keeps `QRToken` records to verify scans and to support audit/replay-safe validation.
4. Student opens `/student/scan` and scans the QR. The front-end posts the raw token payload to the `POST /student/scan/process` endpoint.
5. Backend validation pipeline:
   - Verify token signature and expiry.
   - Confirm token not revoked and matches an active session.
   - Verify student enrollment (or allow pre-enrollment flows as configured).
   - Optional checks: device binding (registered device), IP heuristics, geolocation proximity (if enabled), beacon signals.
   - Compute `PresenceVerification` and create `AttendanceRecord` with `status` (`present`|`late`|`absent`|`excused`) and metadata.
6. Real-time update emitted via SocketIO to professor dashboard and analytics.

Key implementation points
- Tokens are short-lived and server-issued to limit replay and sharing risks.
- A grace window can be used (`QR_GRACE_PERIOD_SECONDS`) to cover network latency.
- The `SessionRoster` ensures the set of eligible students is snapshotted at session start so later enrollment changes do not alter historic attendance.

## Security and privacy considerations

- Tokens are HMAC-signed (server-held secret `QR_SECRET`) and stored hashed (`token_hash`) in `QRToken` to make tokens non-reversible in storage.
- Device binding: students may register device fingerprints (limited to configured `MAX_REGISTERED_DEVICES`) to increase confidence.
- Geolocation is optional and only used when `ENABLE_GEOLOCATION` is `True`. When `REQUIRE_GEOLOCATION` is `True`, scans without verified location are rejected (use carefully).
- Audit trails: `FraudAlert` and `AttendanceAppeal` tables capture human-reviewable evidence and prevent automatic changes to attendance records.
- Email domain restriction (`ALLOWED_EMAIL_DOMAIN`) prevents registrations outside the institution.

## Configuration (env vars and `config.py`)

Important settings (defaults shown in `config.py`) — set via environment variables or `.env`:

- `SECRET_KEY` — Flask secret (must be set in production)
- `DATABASE_URL` — SQLAlchemy DB URI (default: `sqlite:///attendance.db` in local dev)
- `QR_SECRET` — HMAC secret for tokens (CHANGE in production)
- `QR_EXPIRY_SECONDS` — how long tokens are valid (default 90)
- `QR_ROTATION_INTERVAL` — how often UI rotates tokens (default 30)
- `QR_GRACE_PERIOD_SECONDS` — extra tolerance for latency
- `ALLOWED_EMAIL_DOMAIN` — institution email domain (e.g., `@acem.ac.in`)
- `ENABLE_GEOLOCATION`, `REQUIRE_GEOLOCATION`, `LOCATION_VERIFICATION_RADIUS` — geofence options
- Mail settings: `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `ENABLE_EMAIL_NOTIFICATIONS`
- `LATE_THRESHOLD_MINUTES`, `GRACE_PERIOD_MINUTES` — attendance timing rules

Always use a secure `SECRET_KEY` and strong `QR_SECRET` in production. Store secrets in a secure secrets manager when deploying.

## Installation, development, and running

1. Create and activate a virtual environment:

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and edit environment variables for your environment.

4. Initialize the database and seed sample data (the app factory runs seeding by default when `SEED_INITIAL_DATA` is enabled):

```bash
python app.py
```

5. Run the server (development):

```bash
python app.py
# or, if you use run.py in your setup, run that instead
```

6. Visit `http://localhost:5000` and sign in with test credentials (if seed data is enabled):

- Professor: `professor@acem.ac.in` / `password123`
- Student: `student@acem.ac.in` / `password123`

Notes:
- The app uses Flask-SocketIO for realtime; ensure the transport (eventlet/gevent) is available if you run in production.

## Testing and validation

- Unit tests (if present) live under `tests/`. Run them with:

```bash
python -m unittest discover -s tests -v
```

- To manually validate the QR flow:
  1. Start a class session as a professor.
 2. Note the QR rotation interval and capture one token payload.
 3. Use the student scanner to post a token to `/student/scan/process`.
 4. Verify an `AttendanceRecord` is created and `PresenceVerification` saved.

## API endpoints

The important endpoints (see `app/routes/api.py` and other blueprints):

- `GET /api/health` — basic health check
- `GET /api/sessions/<id>/qr` — retrieve current QR token metadata for a session
- `GET /api/sessions/<id>/attendance` — session attendance list

Auth endpoints (see `app/routes/auth.py`): `POST /auth/login`, `POST /auth/student/register`, `POST /auth/professor/register`, `GET /auth/logout`.

Student and professor front-ends are implemented as server-rendered pages with Jinja2; forms and AJAX calls are wired to the routes in `app/routes/*`.

When extending APIs for mobile or external integrations, prefer token-based auth (JWT) if exposing APIs outside the web UI.

## Templates, front-end notes, and PWA behavior

- Front-end uses Tailwind CSS, FontAwesome, and a small set of custom animations defined in `base.html`.
- `app/static/manifest.json` and `service-worker.js` enable PWA/offline behavior for scanner pages — service worker handles offline queueing and synchronization.
- The student scanner UI supports offline capture: payloads are AES-GCM sealed locally and retried when network connectivity is restored (see `utils/`).

## Utilities and helper scripts

- `app/utils/qr_generator.py` — token creation, HMAC signing, token hashing
- `app/utils/session_generator.py` — create sessions and rosters
- `app/utils/attendance_service.py` — central attendance processing logic used by both scanner and API
- `app/utils/email_service.py` — async email sending and notification templates
- `app/utils/seed_data.py` — seed initial departments, courses, users for local dev

I removed temporary helper scripts created during a previous refactor (`rename_branding.py`, `list_branding_refs.py`, `search_branding_lines.py`) — they are not part of the application.

## Maintenance, scaling, and deployment

- Use a production-grade RDBMS (Postgres recommended) for multi-tenant or large-student populations.
- Deploy behind a WSGI-compatible server (Gunicorn) and configure WebSockets using an async worker or run a separate SocketIO server (eventlet/gevent).
- Persist static files and PWA artifacts to a CDN for scale.
- Rotate `QR_SECRET` carefully — maintain backward compatibility for in-flight session tokens or revoke tokens when rotating.

Scaling tips
- Keep QR token generation and validation fast — token validation is HMAC + DB lookup for `QRToken` and `ClassSession` state.
- Use caching (Redis) for active session state and SocketIO message broker for multi-process websockets.

## Troubleshooting & FAQs

- Q: QR tokens rejected immediately after generation? A: Check `QR_EXPIRY_SECONDS` and server clock skew. Ensure server time is synced (NTP).
- Q: Scanner offline payloads not syncing? A: Inspect `service-worker.js` and browser storage; confirm network retry logic and AES key availability.
- Q: Duplicate attendance records? A: DB unique constraint (`session_id`, `student_id`) prevents duplicates — check client retry behavior and server idempotency.

## Contributing

- Fork the repository and open a pull request. Run tests and ensure new code has clear unit tests.
- Follow the existing code style and avoid changing public API contracts without a migration plan.

## Contact & next steps

If you'd like, I can:
- Generate an OpenAPI spec for the HTTP APIs.
- Add a `docker-compose` development environment with Postgres and Redis.
- Create integration smoke tests for the QR attendance flow.

Open an issue or request which of the next steps you'd like me to take.

---

