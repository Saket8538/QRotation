"""Helpers for taking and using an attendance roster snapshot."""
from app import db
from app.models import Enrollment, SessionRoster


def snapshot_session_roster(session):
    """Capture the active class roster once, when a session starts.

    A student added later must not be retrospectively marked absent for an already
    active/completed session. Calling this function more than once is safe.
    """
    existing_entries = SessionRoster.query.filter_by(session_id=session.id).all()
    if existing_entries:
        session.total_enrolled = len(existing_entries)
        return [entry.student_id for entry in existing_entries]

    enrollments = Enrollment.query.filter_by(
        class_instance_id=session.class_instance_id,
        status='active'
    ).all()

    student_ids = []
    for enrollment in enrollments:
        db.session.add(SessionRoster(
            session_id=session.id,
            student_id=enrollment.student_id,
            enrollment_id=enrollment.id
        ))
        student_ids.append(enrollment.student_id)

    session.total_enrolled = len(student_ids)
    db.session.flush()
    return student_ids


def get_session_roster_student_ids(session, create_if_missing=False):
    """Return the roster snapshot, with a compatibility fallback for legacy data."""
    entries = SessionRoster.query.filter_by(session_id=session.id).all()
    if entries:
        return [entry.student_id for entry in entries]

    if create_if_missing:
        return snapshot_session_roster(session)

    # Sessions created before roster snapshots were introduced retain the old behavior.
    # New empty rosters have total_enrolled=0 and should remain empty.
    if session.status in ('active', 'completed') and session.total_enrolled == 0:
        return []

    return [enrollment.student_id for enrollment in Enrollment.query.filter_by(
        class_instance_id=session.class_instance_id,
        status='active'
    ).all()]
