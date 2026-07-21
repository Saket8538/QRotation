# QRotation — Documentation

QRotation is a production-grade, privacy-first attendance platform built with Python and Flask. It provides secure, rotating QR-based attendance with real-time synchronization, explainable presence signals, fraud review workflows, and tools for professors, students, and administrators.

This README is a deep, developer-focused reference that documents architecture, data models, configuration options, the QR attendance flow, API contract, deployment recommendations, and extension points.

## Submission note

Repository URL
- Public repo: [https://github.com/Saket8538/QRotation.git](https://github.com/Saket8538/QRotation.git)

How Codex and the ChatGPT 5.6 tera model helped
- I used GPT-5.6 early on to reason through the trickiest part of the project: how to make a rotating QR code system that's actually hard to spoof, while still keeping verification fast enough for a professor to use in a live classroom. It helped me weigh trade-offs between short-lived signed tokens vs. rolling secrets, and settle on a design that pairs time-boxed QR rotation with server-side signature validation.

- One of the harder tasks was making attendance decisions explainable rather than a black box. I used GPT-5.6 tera model and set it as advanced mode to help design the scoring logic that surfaces why a check-in was flagged (e.g., timestamp drift, duplicate device fingerprint, GPS mismatch) so professors reviewing the fraud queue get a human-readable reason instead of just "flagged."

Used Codex help in the entire project journey

- I used Codex to handle lots of the repetitive, error-prone plumbing — writing the QR token generation/rotation logic, the WebSocket handlers for real-time sync between the professor's dashboard and student devices, and the session/cookie security config. I reviewed and tightened every Codex-generated function before merging, especially around secret handling and session expiry, since that's where security bugs like to hide.

- Codex helped me a lot to scaffold the admin-facing fraud review workflow (queue UI, approve/reject actions, audit logging), which I then customized for the actual data model and permission checks needed for professors vs. administrators.

Why this project matters
- QRotation is built to make attendance simple, secure, and traceable instead of depending on manual roll calls.
- It supports professor-led classes, student QR scanning, real-time attendance tracking, and reviewable alerts so the whole process feels practical in a real classroom.
- The final result is a project that is not just technically functional, but also understandable as a hackathon submission.

Table of contents
- Submission note
- Overview
- Architecture and key components
- Data model (summary)
- QR token & attendance flow (detailed)
- Security and privacy considerations
- Configuration (env vars and Config)
- Installation, development, and running
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
py -3.12 -m venv .venv
# Windows

6. Visit `http://localhost:5000` and sign in with test credentials (if seed data is enabled):

- Professor: `professor@acem.ac.in` / `password123`
- Student: `student@acem.ac.in` / `password123`

Notes:
- The app uses Flask-SocketIO for realtime; ensure the transport (eventlet/gevent) is available if you run in production.

## Environment variables (`.env` example)

Create a `.env` file from `.env.example` and set values appropriate for your environment. Example keys used by the app (add or remove keys depending on your deployment):

```env
# Flask
SECRET_KEY=changeme_in_production
FLASK_ENV=development

# Database
DATABASE_URL=sqlite:///instance/attendance.db

# QR token
QR_SECRET=very-secret-hmac-key
QR_EXPIRY_SECONDS=90
QR_ROTATION_INTERVAL=30
QR_GRACE_PERIOD_SECONDS=10

# Institution / auth
ALLOWED_EMAIL_DOMAIN=@acem.ac.in

# Geolocation
ENABLE_GEOLOCATION=False
REQUIRE_GEOLOCATION=False
LOCATION_VERIFICATION_RADIUS=100.0

# Mail
MAIL_SERVER=smtp.example.com
MAIL_PORT=587
MAIL_USERNAME=mail@example.com
MAIL_PASSWORD=supersecret
ENABLE_EMAIL_NOTIFICATIONS=False

# App behavior
SEED_INITIAL_DATA=True
```

Set `SECRET_KEY` and `QR_SECRET` to securely generated values in production. Use a secrets manager or environment configuration in your hosting environment rather than committing secrets to source control.

## Database initialization & seeding

Local dev uses SQLite by default. To initialize and seed the database:

```bash
# create and activate venv
python -m venv .venv
.venv\Scripts\activate      # Windows
# install deps
pip install -r requirements.txt
# run the app which will create instance/ and initialize DB (app.py runs seed when enabled)
python app.py
```

Notes:
- If you want Postgres in development, set `DATABASE_URL` to a Postgres URI and run your migrations (the project may use SQLAlchemy's base create_all or a migration tool if configured).
- `app/utils/seed_data.py` contains the sample seeding routines (`create_test_users`, `create_test_class`) used in local dev when `SEED_INITIAL_DATA` is enabled.

## QR payload example and validation pseudocode

Example token payload encoded in the QR (the actual app encodes and signs this, then stores a hashed token in `QRToken`):

```json
{
  "sessionId": "0f8fad5b-d9cb-469f-a165-70867728950e",
  "timestamp": 1736697600000,
  "nonce": "4f2e6b8d9c3a",
  "expiresAt": "2026-01-12T12:00:30Z",
  "signature": "hmac-sha256-hex"
}
```

Server-side validation (high level):

```python
def validate_token(payload):
    # 1. Verify HMAC signature using QR_SECRET
    if not verify_signature(payload, QR_SECRET):
        return False, 'invalid_signature'

    # 2. Verify expiry
    if payload.expiresAt < now():
        return False, 'expired'

    # 3. Lookup QRToken by token hash to ensure it wasn't revoked
    token_hash = hash_token(payload)
    token = QRToken.query.filter_by(token_hash=token_hash).first()
    if not token or token.revoked_at:
        return False, 'revoked_or_missing'

    # 4. Confirm the session is active and within its scheduled window
    session = ClassSession.query.get(payload.sessionId)
    if not session or session.status != 'active':
        return False, 'session_inactive'

    return True, session
```

After validation, the attendance pipeline verifies enrollment, optional device bindings and geolocation, then creates `PresenceVerification` and `AttendanceRecord` entries.

## API examples (curl)

Retrieve a session QR metadata (requires auth cookie or token in your app):

```bash
curl -X GET http://localhost:5000/api/sessions/<SESSION_ID>/qr
```

Emulate posting a scanned token to the server (student scanner behavior):

```bash
curl -X POST http://localhost:5000/student/scan/process \
  -H 'Content-Type: application/json' \
  -d '{"token": "<qr-payload-string>", "device_fingerprint": "abc123", "latitude": 12.34, "longitude": 56.78}'
```

## Developer workflows and guidelines

- Add a new field to a model:
  1. Add the column to the SQLAlchemy model in `app/models.py`.
  2. If you use migrations (Flask-Migrate), create and run a migration; otherwise ensure the new schema is handled in your migration plan.
  3. Update any serializers or `to_dict()` helpers.

- Seeding test data: toggle `SEED_INITIAL_DATA` then run `python app.py` to populate sample users, courses and a test session.

- Debugging tips:
  - Check Flask logs for route and validation errors.
  - Use the Flask shell: `python -c "from app import create_app, db; app=create_app(); app.app_context().push(); from app.models import User; print(User.query.count())"`
  - For SocketIO issues, review client console logs and server event handlers in `app/routes`.

## Running in production

Recommended minimal stack for production:

- Postgres for the database (`DATABASE_URL=postgresql://user:pass@db:5432/qrotation`)
- Redis for SocketIO message queue and caching
- Gunicorn with eventlet (or gevent) workers for WebSocket support

Example Gunicorn command:

```bash
gunicorn -k eventlet -w 1 "app:create_app()" --bind 0.0.0.0:8000
```

Docker / docker-compose (suggested)
- Provide a `docker-compose.yml` with services for `web`, `db` (Postgres), and `redis` to reproduce a production-like environment locally. I can scaffold this for you on request.

## API reference (expanded)

Auth / user
- `POST /auth/login` — JSON or form credentials, returns Set-Cookie session or token
- `POST /auth/student/register` — student registration
- `POST /auth/professor/register` — professor registration

Class & session
- `GET /professor/classes` — list professor classes
- `POST /professor/classes/create` — create class instance (course, semester, section)
- `POST /professor/sessions/<id>/activate` — marks session active and generates QR tokens
- `POST /professor/sessions/<id>/complete` — completes session and optionally auto-marks absentees

Scanner & attendance
- `GET /api/sessions/<id>/qr` — current QR metadata
- `POST /student/scan/process` — submit scanned payload; returns attendance result and verification details

Audit & review
- `GET /professor/sessions/<id>/attendance` — session attendance list with presence verification
- `GET /professor/fraud-alerts` — list pending fraud alerts
- `POST /admin/appeals/<id>/review` — resolve attendance appeals

## Templates & PWA notes (expanded)

- `app/templates/base.html` — core layout, includes SocketIO and client-side helpers.
- Scanner pages register a service worker from `app/static/service-worker.js` and read `app/static/manifest.json` for PWA metadata.
- Offline scanner behavior: the service worker stores encrypted scan payloads in IndexedDB/localStorage and retries submission on network restoration. See `app/static/js/offline-attendance.js` for client-side logic.

## Utilities (expanded)

- `app/utils/qr_generator.py` — contains token creation, `sign_token()`, and `verify_signature()` utilities. Tokens are stored hashed in `QRToken.token_hash` to avoid storing raw tokens.
- `app/utils/attendance_service.py` — centralizes scan processing: `validate_token()`, `verify_enrollment()`, `compute_presence_score()`, and `record_attendance()`.
- `app/utils/email_service.py` — asynchronous email notifications (alerts, appeals, reminders). Email templates live under `app/templates/email/` when present.

## Maintenance, scaling and common pitfalls

- Clock skew: HMAC expiry checks require server clocks be synchronized (NTP). Token expiry mismatches are a frequent source of 'expired' validation failures.
- Revocation and rotation: rotating `QR_SECRET` invalidates tokens; provide a revocation or graceful rotation strategy in your deployment plan.
- Concurrency: use Redis + SocketIO message queue for multi-worker setups to ensure real-time messages propagate across processes.

## Troubleshooting & FAQs (expanded)

- QR rejected after generation: check `QR_EXPIRY_SECONDS` and server time; verify token signature using the same `QR_SECRET` as token issuer.
- Duplicate records: DB unique constraint (`session_id`, `student_id`) blocks duplicates; inspect client retries and idempotency behavior.
- Offline payloads failing to sync: check service worker scope, storage quota, and AES key availability used by the front-end to seal payloads.

## Contributing

- Fork the repository and open a pull request. Run tests and ensure new code has clear unit tests.
- Follow the existing code style and avoid changing public API contracts without a migration plan.

## License

This project is licensed under the MIT License. See the [LICENSE](./LICENSE) file for details.


