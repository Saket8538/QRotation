"""
API routes for AJAX endpoints
"""
from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime
import json
from app import db
from app.models import (
    User, Student, Professor, ClassInstance, ClassSession, 
    Enrollment, AttendanceRecord, Course, AcademicPeriod, Department,
    Notification, PresenceVerification, FraudAlert, DeviceRegistration,
    Intervention
)
from app.utils.qr_generator import QRCodeGenerator
from app.utils.attendance_service import AttendanceScanError, process_attendance_scan
from app.utils.engagement_service import professor_copilot_response, student_success_plan, record_audit_event
from app.utils.time_utils import campus_today

api_bp = Blueprint('api', __name__)


@api_bp.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'OK',
        'timestamp': datetime.utcnow().isoformat(),
        'version': '2.0.0',
        'features': [
            'rotating-qr', 'offline-queue', 'browser-notifications',
            'device-binding', 'behavioral-fraud-signals', 'presence-confidence',
            'attendance-copilot', 'smart-interventions', 'student-success-plans',
            'appeals', 'audit-history', 'sis-dry-run-integration'
        ]
    })


@api_bp.route('/students')
@login_required
def get_students():
    """Get all students (for professor enrollment)"""
    if current_user.role != 'professor':
        return jsonify({'success': False, 'error': 'Access denied'})
    
    students = Student.query.all()
    result = []
    for student in students:
        user = User.query.get(student.user_id)
        if user:
            result.append({
                'id': student.user_id,
                'student_id': student.student_id,
                'name': user.full_name,
                'email': user.email,
                'major': student.major
            })
    
    return jsonify({'success': True, 'data': result})


@api_bp.route('/courses')
@login_required
def get_courses():
    """Get all courses"""
    courses = Course.query.filter_by(is_active=True).all()
    result = [{
        'id': c.id,
        'code': c.code,
        'name': c.name,
        'credits': c.credits
    } for c in courses]
    
    return jsonify({'success': True, 'data': result})


@api_bp.route('/departments')
@login_required
def get_departments():
    """Get all departments"""
    departments = Department.query.filter_by(is_active=True).all()
    result = [{
        'id': d.id,
        'code': d.code,
        'name': d.name
    } for d in departments]
    
    return jsonify({'success': True, 'data': result})


@api_bp.route('/academic-periods')
@login_required
def get_academic_periods():
    """Get all academic periods"""
    periods = AcademicPeriod.query.filter_by(is_active=True).order_by(
        AcademicPeriod.start_date.desc()
    ).all()
    result = [{
        'id': p.id,
        'name': p.name,
        'year': p.year,
        'semester': p.semester,
        'start_date': p.start_date.isoformat(),
        'end_date': p.end_date.isoformat(),
        'is_current': p.is_current
    } for p in periods]
    
    return jsonify({'success': True, 'data': result})


@api_bp.route('/attendance/scan', methods=['POST'])
@login_required
def scan_attendance():
    """Process QR code scan using the same workflow as the student scanner."""
    if current_user.role != 'student':
        return jsonify({'success': False, 'error': 'Only students can scan attendance'})

    data = request.get_json(silent=True) or {}
    qr_data = data.get('qr_data')
    if not qr_data:
        return jsonify({'success': False, 'error': 'No QR data provided'})

    try:
        result = process_attendance_scan(
            current_user.id,
            qr_data,
            request_metadata={
                'user_agent': request.headers.get('User-Agent', 'unknown'),
                'ip_address': request.remote_addr,
                'client_device_id': data.get('device_id'),
                'device_label': data.get('device_label', 'Student device'),
                'offline_queued_at': data.get('offline_queued_at'),
                'offline_signature': data.get('offline_signature')
            },
            location_data=data.get('location'),
            presence_signals=data.get('presence_signals')
        )
        return jsonify({
            'success': True,
            'message': f"Attendance marked: {result['status']}",
            'attendance': {
                'status': result['status'],
                'scanned_at': result['scanned_at'].isoformat(),
                'minutes_late': result['minutes_late'],
                'presence_confidence': result['presence_confidence'],
                'class': {
                    'code': result['course'].code,
                    'name': result['course'].name
                }
            }
        })
    except AttendanceScanError as error:
        response = {'success': False, 'error': error.message, 'code': error.code}
        if error.attendance:
            response['attendance'] = {
                'status': error.attendance.status,
                'scanned_at': error.attendance.scanned_at.isoformat()
            }
        return jsonify(response)
    except Exception:
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Unable to record attendance. Please try again.'}), 500


@api_bp.route('/sessions/<session_id>/qr')
@login_required
def get_session_qr(session_id):
    """Get QR code for a session"""
    if current_user.role != 'professor':
        return jsonify({'success': False, 'error': 'Access denied'})
    
    session = ClassSession.query.get(session_id)
    if not session:
        return jsonify({'success': False, 'error': 'Session not found'})
    
    if session.class_instance.professor_id != current_user.id:
        return jsonify({'success': False, 'error': 'Access denied'})
    
    if session.status != 'active':
        return jsonify({'success': False, 'error': 'Session is not active'})
    
    base_url = request.host_url.rstrip('/')
    qr_data = QRCodeGenerator.generate_secure_qr(session_id, base_url)
    
    return jsonify({
        'success': True,
        'qr_code': qr_data['qr_code'],
        'expires_at': qr_data['expires_at']
    })


@api_bp.route('/sessions/<session_id>/attendance')
@login_required
def get_session_attendance(session_id):
    """Get attendance for a session"""
    session = ClassSession.query.get(session_id)
    if not session:
        return jsonify({'success': False, 'error': 'Session not found'})
    
    ci = session.class_instance
    
    # Check access
    if current_user.role == 'professor' and ci.professor_id != current_user.id:
        return jsonify({'success': False, 'error': 'Access denied'})
    if current_user.role not in ('student', 'professor'):
        return jsonify({'success': False, 'error': 'Access denied'}), 403

    records_query = AttendanceRecord.query.filter_by(session_id=session_id)
    if current_user.role == 'student':
        # A student can only see their own attendance, never the class roster.
        records_query = records_query.filter_by(student_id=current_user.id)
    records = records_query.all()
    
    result = []
    for record in records:
        student = Student.query.filter_by(user_id=record.student_id).first()
        user = User.query.get(record.student_id)
        
        if student and user:
            presence = PresenceVerification.query.filter_by(attendance_id=record.id).first()
            result.append({
                'id': record.id,
                'student_id': student.student_id,
                'name': user.full_name,
                'status': record.status,
                'scanned_at': record.scanned_at.isoformat(),
                'minutes_late': record.minutes_late,
                'presence_confidence': presence.confidence_score if presence else None,
                'fraud_alerts': FraudAlert.query.filter_by(attendance_id=record.id).count()
            })
    
    # Get stats
    enrolled = Enrollment.query.filter_by(
        class_instance_id=ci.id,
        status='active'
    ).count()
    
    present = sum(1 for r in result if r['status'] == 'present')
    late = sum(1 for r in result if r['status'] == 'late')
    excused = sum(1 for r in result if r['status'] == 'excused')
    if current_user.role == 'student':
        # Do not leak roster size or other students' attendance to a student.
        enrolled = 1
        absent = sum(1 for r in result if r['status'] == 'absent')
    else:
        absent = enrolled - len(result)
    
    return jsonify({
        'success': True,
        'attendance': result,
        'stats': {
            'present': present,
            'late': late,
            'absent': absent,
            'excused': excused,
            'total': enrolled
        }
    })


@api_bp.route('/notifications')
@login_required
def get_notifications():
    """Return the signed-in user's notification centre data."""
    limit = min(max(request.args.get('limit', 20, type=int), 1), 50)
    notifications = Notification.query.filter_by(user_id=current_user.id).order_by(
        Notification.created_at.desc()
    ).limit(limit).all()
    unread_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return jsonify({
        'success': True,
        'unread_count': unread_count,
        'notifications': [{
            'id': item.id,
            'type': item.type,
            'title': item.title,
            'message': item.message or '',
            'link': item.link,
            'is_read': bool(item.is_read),
            'created_at': item.created_at.isoformat() if item.created_at else None
        } for item in notifications]
    })


@api_bp.route('/notifications/<notification_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    notification = Notification.query.filter_by(id=notification_id, user_id=current_user.id).first()
    if not notification:
        return jsonify({'success': False, 'error': 'Notification not found'}), 404
    notification.is_read = True
    db.session.commit()
    return jsonify({'success': True})


@api_bp.route('/notifications/read-all', methods=['POST'])
@login_required
def mark_all_notifications_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update(
        {'is_read': True}, synchronize_session=False
    )
    db.session.commit()
    return jsonify({'success': True})


@api_bp.route('/student/success-plans')
@login_required
def get_student_success_plans():
    if current_user.role != 'student':
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    enrollments = Enrollment.query.filter_by(student_id=current_user.id, status='active').all()
    plans = []
    for enrollment in enrollments:
        plan = student_success_plan(enrollment.class_instance, current_user.id)
        plan.update({
            'class_code': enrollment.class_instance.class_code,
            'course_name': enrollment.class_instance.course.name
        })
        plans.append(plan)
    return jsonify({'success': True, 'plans': plans})


@api_bp.route('/student/devices')
@login_required
def get_student_devices():
    if current_user.role != 'student':
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    devices = DeviceRegistration.query.filter_by(user_id=current_user.id).order_by(
        DeviceRegistration.last_seen_at.desc()
    ).all()
    return jsonify({'success': True, 'max_devices': current_app.config.get('MAX_REGISTERED_DEVICES', 2), 'devices': [
        {'id': device.id, 'label': device.label, 'is_active': device.is_active,
         'last_seen_at': device.last_seen_at.isoformat() if device.last_seen_at else None}
        for device in devices
    ]})


@api_bp.route('/student/devices/<device_id>/revoke', methods=['POST'])
@login_required
def revoke_student_device(device_id):
    if current_user.role != 'student':
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    device = DeviceRegistration.query.filter_by(id=device_id, user_id=current_user.id).first()
    if not device:
        return jsonify({'success': False, 'error': 'Device not found'}), 404
    device.is_active = False
    record_audit_event(current_user.id, 'device_revoked', 'device_registration', device.id,
                       ip_address=request.remote_addr)
    db.session.commit()
    return jsonify({'success': True})


@api_bp.route('/professor/copilot', methods=['POST'])
@login_required
def professor_copilot():
    if current_user.role != 'professor':
        return jsonify({'success': False, 'error': 'Professor access required'}), 403
    data = request.get_json(silent=True) or {}
    question = str(data.get('question', '')).strip()
    if not question:
        return jsonify({'success': False, 'error': 'Ask a question about your attendance data.'}), 400
    return jsonify({'success': True, 'result': professor_copilot_response(current_user.id, question)})


@api_bp.route('/professor/interventions', methods=['GET', 'POST'])
@login_required
def professor_interventions():
    if current_user.role != 'professor':
        return jsonify({'success': False, 'error': 'Professor access required'}), 403
    if request.method == 'GET':
        items = Intervention.query.filter_by(professor_id=current_user.id).order_by(
            Intervention.created_at.desc()).limit(100).all()
        return jsonify({'success': True, 'interventions': [{
            'id': item.id, 'student_id': item.student_id, 'class_id': item.class_instance_id,
            'type': item.intervention_type, 'message': item.message, 'status': item.status,
            'created_at': item.created_at.isoformat() if item.created_at else None
        } for item in items]})

    data = request.get_json(silent=True) or {}
    class_instance = ClassInstance.query.filter_by(
        id=data.get('class_id'), professor_id=current_user.id, is_active=True
    ).first()
    enrollment = Enrollment.query.filter_by(
        class_instance_id=data.get('class_id'), student_id=data.get('student_id'), status='active'
    ).first()
    message = str(data.get('message', '')).strip()
    intervention_type = str(data.get('type', 'reminder')).strip().lower()
    allowed_types = {'reminder', 'make_up', 'excused', 'counselling'}
    if not class_instance or not enrollment or not message or intervention_type not in allowed_types:
        return jsonify({'success': False, 'error': 'Valid class, enrolled student, type, and message are required.'}), 400
    intervention = Intervention(
        professor_id=current_user.id, student_id=enrollment.student_id,
        class_instance_id=class_instance.id, intervention_type=intervention_type,
        message=message
    )
    db.session.add(intervention)
    db.session.add(Notification(
        user_id=enrollment.student_id, type='intervention', title='Attendance support',
        message=message, link='/student/dashboard', extra_data=json.dumps({'intervention_type': intervention_type})
    ))
    db.session.flush()
    record_audit_event(current_user.id, 'intervention_created', 'intervention', intervention.id,
                       {'student_id': enrollment.student_id, 'class_id': class_instance.id}, request.remote_addr)
    db.session.commit()
    return jsonify({'success': True, 'intervention_id': intervention.id}), 201


@api_bp.route('/professor/interventions/suggestions')
@login_required
def intervention_suggestions():
    if current_user.role != 'professor':
        return jsonify({'success': False, 'error': 'Professor access required'}), 403
    result = professor_copilot_response(current_user.id, 'Which students are at risk?')
    return jsonify({'success': True, 'suggestions': result.get('actions', []), 'classes': result.get('classes', [])})


@api_bp.route('/professor/interventions/<intervention_id>/complete', methods=['POST'])
@login_required
def complete_intervention(intervention_id):
    if current_user.role != 'professor':
        return jsonify({'success': False, 'error': 'Professor access required'}), 403
    item = Intervention.query.filter_by(id=intervention_id, professor_id=current_user.id).first()
    if not item:
        return jsonify({'success': False, 'error': 'Intervention not found'}), 404
    item.status = 'completed'
    item.completed_at = datetime.utcnow()
    record_audit_event(current_user.id, 'intervention_completed', 'intervention', item.id,
                       ip_address=request.remote_addr)
    db.session.commit()
    return jsonify({'success': True})


@api_bp.route('/integrations/sis/preview')
@login_required
def sis_preview():
    if current_user.role not in ('professor', 'admin'):
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    classes = ClassInstance.query.filter_by(professor_id=current_user.id, is_active=True).all() if current_user.role == 'professor' else ClassInstance.query.filter_by(is_active=True).all()
    return jsonify({'success': True, 'mode': 'dry_run', 'classes': [{
        'class_code': item.class_code, 'course_code': item.course.code,
        'enrolled_students': Enrollment.query.filter_by(class_instance_id=item.id, status='active').count()
    } for item in classes]})


@api_bp.route('/integrations/sis/import', methods=['POST'])
@login_required
def sis_import():
    if current_user.role not in ('professor', 'admin'):
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    data = request.get_json(silent=True) or {}
    students = data.get('students', [])
    if not isinstance(students, list):
        return jsonify({'success': False, 'error': 'students must be an array'}), 400
    valid = [row for row in students if isinstance(row, dict) and row.get('email') and row.get('student_id')]
    record_audit_event(current_user.id, 'sis_import_preview', 'integration', 'sis',
                       {'received': len(students), 'valid': len(valid)}, request.remote_addr)
    db.session.commit()
    return jsonify({'success': True, 'mode': 'dry_run', 'received': len(students), 'valid': len(valid),
                    'message': 'Validated only; connect the institution SIS adapter to commit changes.'})


@api_bp.route('/student/today-stats')
@login_required
def student_today_stats():
    """Get student's today attendance stats"""
    if current_user.role != 'student':
        return jsonify({'success': False, 'error': 'Access denied'})
    
    today = campus_today()
    
    records = db.session.query(AttendanceRecord).join(ClassSession).filter(
        AttendanceRecord.student_id == current_user.id,
        ClassSession.date == today
    ).all()
    
    stats = {
        'scans_today': len(records),
        'present': sum(1 for r in records if r.status == 'present'),
        'late': sum(1 for r in records if r.status == 'late'),
        'absent': sum(1 for r in records if r.status == 'absent'),
        'excused': sum(1 for r in records if r.status == 'excused')
    }
    
    return jsonify({'success': True, 'stats': stats})
