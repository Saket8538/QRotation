"""Hackathon-facing intelligence, anti-fraud, and audit helpers.

All recommendations are explainable and derived from attendance data; no student
profile is sent to a third-party AI provider.
"""
import hashlib
import json
import math
from datetime import timedelta

from flask import current_app

from app import db
from app.models import (
    AttendanceRecord, AuditLog, ClassInstance, ClassSession, DeviceRegistration,
    FraudAlert, PresenceVerification, User
)
from app.utils.time_utils import campus_today, utc_now_naive


class DevicePolicyError(Exception):
    """Raised when a device cannot be safely registered for a student."""


def record_audit_event(actor_id, action, entity_type, entity_id, details=None, ip_address=None):
    """Append an audit event to the active database transaction."""
    db.session.add(AuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        details=json.dumps(details or {}, separators=(',', ':')),
        ip_address=(ip_address or '')[:50]
    ))


def register_student_device(user_id, device_id, user_agent='', label='Student device'):
    """Bind an opaque browser-generated device id, up to the configured limit."""
    if not isinstance(device_id, str) or not 16 <= len(device_id) <= 128:
        return None

    device_hash = hashlib.sha256(device_id.encode('utf-8')).hexdigest()
    existing = DeviceRegistration.query.filter_by(device_hash=device_hash).first()
    now = utc_now_naive()
    if existing:
        if existing.user_id != user_id:
            raise DevicePolicyError('This device is already registered to another student account.')
        existing.last_seen_at = now
        existing.user_agent = user_agent[:255]
        existing.is_active = True
        return existing

    max_devices = current_app.config.get('MAX_REGISTERED_DEVICES', 2)
    active_devices = DeviceRegistration.query.filter_by(user_id=user_id, is_active=True).count()
    if active_devices >= max_devices:
        raise DevicePolicyError(
            f'You have reached the {max_devices}-device limit. Remove an old device from your profile first.'
        )

    registration = DeviceRegistration(
        user_id=user_id,
        device_hash=device_hash,
        label=(label or 'Student device')[:100],
        user_agent=user_agent[:255],
        first_seen_at=now,
        last_seen_at=now
    )
    db.session.add(registration)
    db.session.flush()
    return registration


def verify_classroom_beacon(session, presence_signals):
    """Validate an optional Web Bluetooth beacon name against room configuration."""
    beacon_id = (presence_signals or {}).get('beacon_id')
    if not beacon_id:
        return False, None
    try:
        configured = json.loads(current_app.config.get('CLASSROOM_BEACONS', '{}'))
    except (TypeError, json.JSONDecodeError):
        configured = {}
    expected = configured.get(session.room_location, [])
    if isinstance(expected, str):
        expected = [expected]
    verified = str(beacon_id) in {str(item) for item in expected}
    return verified, str(beacon_id)[:100]


def create_presence_verification(attendance, location_verified, device_verified, beacon_verified, beacon_id=None):
    """Store an explainable confidence score; it does not change attendance status."""
    score = 45  # server-issued QR token
    if device_verified:
        score += 25
    if location_verified:
        score += 20
    if beacon_verified:
        score += 10

    details = {
        'signals': {
            'rotating_qr': True,
            'registered_device': bool(device_verified),
            'geofence': bool(location_verified),
            'bluetooth_beacon': bool(beacon_verified)
        }
    }
    if beacon_id:
        details['beacon_name'] = beacon_id
    verification = PresenceVerification(
        attendance_id=attendance.id,
        qr_verified=True,
        device_verified=bool(device_verified),
        location_verified=bool(location_verified),
        beacon_verified=bool(beacon_verified),
        confidence_score=min(score, 100),
        details=json.dumps(details, separators=(',', ':'))
    )
    db.session.add(verification)
    return verification


def create_fraud_signals(attendance, session, device_hash=None):
    """Create reviewable alerts for meaningful suspicious patterns.

    QR sharing by itself is not treated as fraud: a classroom display is expected to
    be scanned by many students. Alerts require a stronger signal, such as the same
    bound device appearing against multiple student accounts or unusually rapid
    multi-network token use. Faculty review every alert.
    """
    alerts = []
    if device_hash:
        other_device_scans = AttendanceRecord.query.filter(
            AttendanceRecord.session_id == session.id,
            AttendanceRecord.device_fingerprint == device_hash,
            AttendanceRecord.student_id != attendance.student_id
        ).count()
        if other_device_scans:
            alerts.append(FraudAlert(
                session_id=session.id,
                attendance_id=attendance.id,
                student_id=attendance.student_id,
                alert_type='shared_registered_device',
                severity='high',
                evidence=json.dumps({'other_scans': other_device_scans})
            ))

    if attendance.qr_secret_used:
        window = current_app.config.get('FRAUD_SCAN_WINDOW_SECONDS', 8)
        threshold = current_app.config.get('FRAUD_SHARED_QR_MIN_SCANS', 8)
        since = attendance.scanned_at - timedelta(seconds=window)
        token_scans = AttendanceRecord.query.filter(
            AttendanceRecord.session_id == session.id,
            AttendanceRecord.qr_secret_used == attendance.qr_secret_used,
            AttendanceRecord.scanned_at >= since
        ).all()
        distinct_ips = {record.ip_address for record in token_scans if record.ip_address}
        if len(token_scans) >= threshold and len(distinct_ips) >= 3:
            alerts.append(FraudAlert(
                session_id=session.id,
                attendance_id=attendance.id,
                alert_type='rapid_multi_network_qr_use',
                severity='low',
                evidence=json.dumps({
                    'scans_in_window': len(token_scans),
                    'distinct_ips': len(distinct_ips),
                    'window_seconds': window
                })
            ))

    for alert in alerts:
        db.session.add(alert)
    return alerts


def student_success_plan(class_instance, student_id, threshold=None):
    """Return an explainable attendance forecast for one student and class."""
    threshold = threshold or current_app.config.get('LOW_ATTENDANCE_THRESHOLD', 75)
    completed = ClassSession.query.filter_by(
        class_instance_id=class_instance.id,
        status='completed'
    ).all()
    completed_ids = [session.id for session in completed]
    attended = AttendanceRecord.query.filter(
        AttendanceRecord.student_id == student_id,
        AttendanceRecord.session_id.in_(completed_ids) if completed_ids else False,
        AttendanceRecord.status.in_(['present', 'late', 'excused'])
    ).count() if completed_ids else 0
    late_count = AttendanceRecord.query.filter(
        AttendanceRecord.student_id == student_id,
        AttendanceRecord.session_id.in_(completed_ids) if completed_ids else False,
        AttendanceRecord.status == 'late'
    ).count() if completed_ids else 0

    upcoming = ClassSession.query.filter(
        ClassSession.class_instance_id == class_instance.id,
        ClassSession.status == 'scheduled',
        ClassSession.date >= campus_today()
    ).count()
    completed_count = len(completed)
    projected_total = completed_count + upcoming
    current_rate = round(attended / completed_count * 100) if completed_count else 0
    required_total = math.ceil((threshold / 100) * projected_total) if projected_total else 0
    needs_from_remaining = max(0, required_total - attended)
    best_possible = round((attended + upcoming) / projected_total * 100) if projected_total else 100

    if not projected_total:
        risk = 'on_track'
        message = 'No completed or upcoming sessions are available for a forecast yet.'
    elif best_possible < threshold:
        risk = 'high'
        message = f'Even perfect attendance from now projects to {best_possible}%, below the {threshold}% target.'
    elif current_rate < threshold and upcoming == 0:
        risk = 'high'
        message = f'Your completed-session attendance is {current_rate}%, below the {threshold}% target; ask faculty about an approved recovery option.'
    elif current_rate < threshold:
        risk = 'medium'
        message = f'Attend at least {needs_from_remaining} of the next {upcoming} sessions to reach {threshold}%.'
    else:
        risk = 'on_track'
        message = f'You are on track. Attend {needs_from_remaining} of the next {upcoming} sessions to stay above {threshold}%.'

    return {
        'class_id': class_instance.id,
        'current_rate': current_rate,
        'threshold': threshold,
        'completed_sessions': completed_count,
        'upcoming_sessions': upcoming,
        'required_attendances': needs_from_remaining,
        'best_possible_rate': best_possible,
        'late_count': late_count,
        'risk': risk,
        'message': message
    }


def professor_copilot_response(professor_id, question):
    """Generate transparent faculty insight and intervention suggestions."""
    from app.utils.reports import generate_class_summary

    question = (question or '').strip()
    classes = ClassInstance.query.filter_by(professor_id=professor_id, is_active=True).all()
    class_summaries = []
    actions = []
    for class_instance in classes:
        summary = generate_class_summary(class_instance.id)
        if not summary:
            continue
        at_risk = [student for student in summary['attendance_data'] if student['attendance_rate'] < current_app.config.get('LOW_ATTENDANCE_THRESHOLD', 75)]
        class_summaries.append({
            'class_id': class_instance.id,
            'class_code': class_instance.class_code,
            'course_name': class_instance.course.name,
            'average_attendance': summary['average_attendance'],
            'at_risk_count': len(at_risk),
            'late_count': sum(student['late_count'] for student in summary['attendance_data'])
        })
        for student in at_risk[:3]:
            user = User.query.filter_by(email=student['email']).first()
            if user:
                actions.append({
                    'student_id': user.id,
                    'student_name': student['student_name'],
                    'class_id': class_instance.id,
                    'class_code': class_instance.class_code,
                    'type': 'reminder',
                    'message': f"Your attendance in {class_instance.course.code} is {student['attendance_rate']}%. Let's make a recovery plan."
                })

    low_classes = [item for item in class_summaries if item['average_attendance'] < 75]
    total_risk = sum(item['at_risk_count'] for item in class_summaries)
    lower_question = question.lower()
    if 'why' in lower_question or 'fall' in lower_question or 'drop' in lower_question:
        drivers = ', '.join(
            f"{item['class_code']} ({item['average_attendance']}%, {item['late_count']} late records)"
            for item in sorted(class_summaries, key=lambda item: item['average_attendance'])[:3]
        ) or 'there is not enough completed-session data yet'
        answer = f"Attendance pressure is strongest in {drivers}. Review repeated late arrivals and offer an early intervention before finalising absences."
    elif 'risk' in lower_question or 'student' in lower_question:
        answer = f"I found {total_risk} student risk signal(s) across {len(class_summaries)} active classes. Start with the lowest attendance rates and send a supportive reminder or make-up option."
    else:
        answer = f"Your portfolio has {len(class_summaries)} active classes, {len(low_classes)} below the 75% target, and {total_risk} student risk signal(s). Ask about risk, attendance decline, or recommended interventions."

    return {
        'answer': answer,
        'classes': class_summaries,
        'actions': actions[:8],
        'generated_from': 'attendance records, roster snapshots, and late-arrival patterns'
    }
