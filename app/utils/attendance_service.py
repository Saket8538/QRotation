"""Single, transaction-safe attendance scan workflow used by every endpoint."""
import json

from sqlalchemy.exc import IntegrityError

from app import db
from app.models import AttendanceRecord, ClassSession, Enrollment, FraudAlert, Notification
from app.utils.engagement_service import (
    DevicePolicyError, create_fraud_signals, create_presence_verification,
    record_audit_event, register_student_device, verify_classroom_beacon
)
from app.utils.qr_generator import QRCodeGenerator
from app.utils.time_utils import calculate_lateness, utc_now_naive


class AttendanceScanError(Exception):
    """A safe, expected attendance failure that can be shown to the student."""

    def __init__(self, message, code='attendance_error', attendance=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.attendance = attendance


def _verify_location(session, location_data):
    """Validate and optionally verify supplied location data."""
    from flask import current_app

    if not current_app.config.get('ENABLE_GEOLOCATION', False):
        return None, None, False

    if not location_data:
        if current_app.config.get('REQUIRE_GEOLOCATION', False):
            raise AttendanceScanError('Location permission is required to mark attendance.', 'location_required')
        return None, None, False

    try:
        latitude = float(location_data['latitude'])
        longitude = float(location_data['longitude'])
    except (KeyError, TypeError, ValueError):
        raise AttendanceScanError('Invalid location data. Please try again.', 'invalid_location')

    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise AttendanceScanError('Invalid location data. Please try again.', 'invalid_location')

    room = session.room_location
    classroom = current_app.config.get('CLASSROOM_LOCATIONS', {}).get(room)
    if not classroom:
        if current_app.config.get('REQUIRE_GEOLOCATION', False):
            raise AttendanceScanError('This session has no configured classroom location.', 'location_not_configured')
        return latitude, longitude, False

    from math import asin, cos, radians, sin, sqrt

    campus_lat = float(classroom['lat'])
    campus_lng = float(classroom['lng'])
    lat1, lng1, lat2, lng2 = map(radians, [latitude, longitude, campus_lat, campus_lng])
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lng2 - lng1) / 2) ** 2
    distance = 6_371_000 * 2 * asin(sqrt(a))
    verified = distance <= float(classroom.get('radius', 100))

    if current_app.config.get('REQUIRE_GEOLOCATION', False) and not verified:
        raise AttendanceScanError(
            f'You must be within {int(classroom.get("radius", 100))}m of the classroom.',
            'location_outside_classroom'
        )
    return latitude, longitude, verified, distance


def process_attendance_scan(student_id, qr_data, request_metadata=None, location_data=None, presence_signals=None):
    """Validate a scan and create exactly one attendance record for a student."""
    validation = QRCodeGenerator.validate_qr(qr_data)
    if not validation['isValid']:
        raise AttendanceScanError(validation['error'], 'invalid_qr')

    session = db.session.get(ClassSession, validation['sessionId'])
    if not session or session.status != 'active' or not session.is_active:
        raise AttendanceScanError('Session is not active.', 'session_not_active')

    enrollment = Enrollment.query.filter_by(
        student_id=student_id,
        class_instance_id=session.class_instance_id,
        status='active'
    ).first()
    if not enrollment:
        raise AttendanceScanError('You are not enrolled in this class.', 'not_enrolled')

    existing = AttendanceRecord.query.filter_by(session_id=session.id, student_id=student_id).first()
    if existing:
        raise AttendanceScanError('Attendance already marked.', 'already_marked', existing)

    request_metadata = request_metadata or {}
    try:
        device = register_student_device(
            student_id,
            request_metadata.get('client_device_id'),
            request_metadata.get('user_agent', ''),
            request_metadata.get('device_label', 'Student device')
        )
    except DevicePolicyError as error:
        db.session.add(FraudAlert(
            session_id=session.id,
            student_id=student_id,
            alert_type='device_binding_conflict',
            severity='high',
            evidence=json.dumps({'message': str(error)})
        ))
        db.session.commit()
        raise AttendanceScanError(str(error), 'device_policy')

    location_result = _verify_location(session, location_data)
    if len(location_result) == 3:
        latitude, longitude, location_verified = location_result
        location_distance = None
    else:
        latitude, longitude, location_verified, location_distance = location_result

    beacon_verified, beacon_id = verify_classroom_beacon(session, presence_signals)

    minutes_late, is_late = calculate_lateness(session)
    scanned_at = utc_now_naive()
    status = 'late' if is_late else 'present'

    try:
        # The uniqueness constraint is the source of truth. The savepoint lets a
        # concurrent duplicate scan become a normal "already marked" response.
        with db.session.begin_nested():
            attendance = AttendanceRecord(
                session_id=session.id,
                student_id=student_id,
                scanned_at=scanned_at,
                status=status,
                minutes_late=minutes_late if is_late else 0,
                # Store the non-reversible device hash, not raw device/browser data.
                device_fingerprint=device.device_hash if device else None,
                ip_address=request_metadata.get('ip_address', '')[:50],
                qr_secret_used=validation.get('tokenId'),
                latitude=latitude,
                longitude=longitude,
                location_verified=location_verified,
                location_distance=location_distance
            )
            db.session.add(attendance)
            db.session.flush()
    except IntegrityError:
        existing = AttendanceRecord.query.filter_by(session_id=session.id, student_id=student_id).first()
        if existing:
            raise AttendanceScanError('Attendance already marked.', 'already_marked', existing)
        raise

    course = session.class_instance.course
    db.session.add(Notification(
        user_id=student_id,
        type='attendance_recorded',
        title='Attendance Recorded',
        message=f'Marked {status} for {course.code}',
        link='/student/attendance',
        session_id=session.id,
        extra_data=json.dumps({
            'className': course.code,
            'status': status,
            'minutesLate': minutes_late if is_late else 0
        })
    ))
    presence = create_presence_verification(
        attendance,
        location_verified=location_verified,
        device_verified=device is not None,
        beacon_verified=beacon_verified,
        beacon_id=beacon_id
    )
    fraud_alerts = create_fraud_signals(
        attendance,
        session,
        device_hash=device.device_hash if device else None
    )
    record_audit_event(
        student_id,
        'attendance_recorded',
        'attendance_record',
        attendance.id,
        details={
            'session_id': session.id,
            'status': status,
            'presence_confidence': presence.confidence_score,
            'offline_queued_at': request_metadata.get('offline_queued_at'),
            'offline_signature_present': bool(request_metadata.get('offline_signature'))
        },
        ip_address=request_metadata.get('ip_address')
    )

    # Keep the cached value consistent with the database even after a later manual edit.
    session.attendance_count = AttendanceRecord.query.filter_by(session_id=session.id).filter(
        AttendanceRecord.status.in_(['present', 'late', 'excused'])
    ).count()
    db.session.commit()

    return {
        'session': session,
        'attendance': attendance,
        'course': course,
        'status': status,
        'minutes_late': minutes_late if is_late else 0,
        'scanned_at': scanned_at,
        'attendance_count': session.attendance_count,
        'presence_confidence': presence.confidence_score,
        'fraud_alert_count': len(fraud_alerts)
    }
