"""Time helpers for scheduling and attendance calculations."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app, has_app_context

from config import Config


def campus_timezone():
    """Return the configured campus timezone, with a safe UTC fallback."""
    timezone_name = (
        current_app.config.get('CAMPUS_TIMEZONE', Config.CAMPUS_TIMEZONE)
        if has_app_context()
        else Config.CAMPUS_TIMEZONE
    )
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def campus_now():
    """Current timezone-aware time at the campus."""
    return datetime.now(campus_timezone())


def campus_today():
    """Current date at the campus."""
    return campus_now().date()


def utc_now_naive():
    """UTC for existing timezone-naive database columns.

    New database columns should eventually be migrated to timezone-aware values. This
    helper keeps the current schema compatible while preventing server-local time from
    changing attendance timestamps.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def calculate_lateness(session):
    """Return ``(minutes_late, is_late)`` using the campus timezone."""
    start_time = datetime.strptime(session.start_time, '%H:%M').time()
    scheduled_start = datetime.combine(session.date, start_time, tzinfo=campus_timezone())
    minutes_late = max(0, int((campus_now() - scheduled_start).total_seconds() / 60))
    threshold = current_app.config.get('LATE_THRESHOLD_MINUTES', Config.LATE_THRESHOLD_MINUTES)
    return minutes_late, minutes_late > threshold
