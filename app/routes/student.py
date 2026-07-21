"""
Student routes for dashboard, classes, attendance, and QR scanning
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime
from app import db, socketio
from app.models import (
    User, Student, ClassInstance, ClassSession, Enrollment, 
    AttendanceRecord, AttendanceAppeal, Course, AcademicPeriod, Notification,
    DeviceRegistration
)
from app.utils.attendance_service import AttendanceScanError, process_attendance_scan
from app.utils.engagement_service import record_audit_event, student_success_plan
from app.utils.time_utils import campus_today

student_bp = Blueprint('student', __name__)


def student_required(f):
    """Decorator to ensure user is a student"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'student':
            flash('Access denied. Student account required.', 'error')
            return redirect(url_for('auth.student_login'))
        return f(*args, **kwargs)
    return decorated_function


@student_bp.route('/')
@login_required
@student_required
def home():
    """Canonical student landing URL."""
    return redirect(url_for('student.dashboard'))


@student_bp.route('/dashboard')
@login_required
@student_required
def dashboard():
    """Student dashboard"""
    student = Student.query.filter_by(user_id=current_user.id).first()
    
    if not student:
        flash('Student profile not found.', 'error')
        return redirect(url_for('main.index'))
    
    # Get enrolled classes (student_id in Enrollment references students.user_id)
    enrollments = Enrollment.query.filter_by(
        student_id=student.user_id, 
        status='active'
    ).all()
    
    classes = []
    today = campus_today()
    today_str = today.strftime('%A')  # Day name like 'Monday'
    
    for enrollment in enrollments:
        class_instance = enrollment.class_instance
        course = class_instance.course
        
        # Check if class meets today based on schedule
        days_list = class_instance.days_list
        scheduled_today = today_str in days_list
        
        # Get attendance stats
        total_sessions = ClassSession.query.filter_by(
            class_instance_id=class_instance.id,
            status='completed'
        ).count()
        
        attended_sessions = db.session.query(AttendanceRecord).join(ClassSession).filter(
            ClassSession.class_instance_id == class_instance.id,
            ClassSession.status == 'completed',
            AttendanceRecord.student_id == current_user.id,
            AttendanceRecord.status.in_(['present', 'late', 'excused'])
        ).count()
        
        attendance_rate = round((attended_sessions / total_sessions * 100)) if total_sessions > 0 else 0
        
        # Get today's session if any
        today_session = ClassSession.query.filter_by(
            class_instance_id=class_instance.id,
            date=today
        ).first()
        
        # Check if there's an active session today
        has_active_session = today_session and today_session.status == 'active' if today_session else False
        
        # Class meets today if scheduled OR has an active session
        meets_today = scheduled_today or has_active_session
        
        classes.append({
            'id': class_instance.id,
            'code': course.code,
            'name': course.name,
            'room': class_instance.room_location,
            'schedule': f"{', '.join(days_list)} {class_instance.start_time}-{class_instance.end_time}",
            'meets_today': meets_today,
            'attendance_rate': attendance_rate,
            'total_sessions': total_sessions,
            'attended_sessions': attended_sessions,
            'today_session': today_session,
            'has_active_session': has_active_session,
            'success_plan': student_success_plan(class_instance, current_user.id),
            'sessions_count': total_sessions
        })
    
    # Get today's attendance stats
    today_stats = {
        'scans_today': 0,
        'present': 0,
        'late': 0,
        'absent': 0
    }
    
    today_records = db.session.query(AttendanceRecord).join(ClassSession).filter(
        AttendanceRecord.student_id == current_user.id,
        ClassSession.date == today
    ).all()
    
    today_stats['scans_today'] = len(today_records)
    for record in today_records:
        if record.status == 'present':
            today_stats['present'] += 1
        elif record.status == 'late':
            today_stats['late'] += 1
        elif record.status == 'absent':
            today_stats['absent'] += 1
    
    # Get recent notifications
    notifications = Notification.query.filter_by(
        user_id=current_user.id
    ).order_by(Notification.created_at.desc()).limit(5).all()

    overall_attendance = round(
        sum(class_data['attendance_rate'] for class_data in classes) / len(classes)
    ) if classes else 0
    
    return render_template('student/dashboard.html',
        student=student,
        classes=classes,
        today_stats=today_stats,
        notifications=notifications,
        overall_attendance=overall_attendance,
        current_time=datetime.now()
    )


@student_bp.route('/classes')
@login_required
@student_required
def classes():
    """Student classes list"""
    student = Student.query.filter_by(user_id=current_user.id).first()
    
    enrollments = Enrollment.query.filter_by(
        student_id=current_user.id,
        status='active'
    ).all()
    
    classes = []
    for enrollment in enrollments:
        class_instance = enrollment.class_instance
        course = class_instance.course
        professor = User.query.get(class_instance.professor_id)
        
        # Get attendance stats
        total_sessions = ClassSession.query.filter_by(
            class_instance_id=class_instance.id,
            status='completed'
        ).count()
        
        attended_sessions = db.session.query(AttendanceRecord).join(ClassSession).filter(
            ClassSession.class_instance_id == class_instance.id,
            ClassSession.status == 'completed',
            AttendanceRecord.student_id == current_user.id,
            AttendanceRecord.status.in_(['present', 'late', 'excused'])
        ).count()
        
        attendance_rate = round((attended_sessions / total_sessions * 100)) if total_sessions > 0 else 0
        
        classes.append({
            'id': class_instance.id,
            'code': course.code,
            'name': course.name,
            'description': course.description,
            'credits': course.credits,
            'professor': professor.full_name if professor else 'Unknown',
            'professor_email': professor.email if professor else '',
            'room': class_instance.room_location,
            'schedule': f"{', '.join(class_instance.days_list)} {class_instance.start_time}-{class_instance.end_time}",
            'attendance_rate': attendance_rate,
            'total_sessions': total_sessions,
            'attended_sessions': attended_sessions,
            'enrollment_date': enrollment.enrollment_date
        })
    
    return render_template('student/classes.html', classes=classes)


@student_bp.route('/classes/<class_id>')
@login_required
@student_required
def class_detail(class_id):
    """Class detail page"""
    enrollment = Enrollment.query.filter_by(
        student_id=current_user.id,
        class_instance_id=class_id,
        status='active'
    ).first()
    
    if not enrollment:
        flash('You are not enrolled in this class.', 'error')
        return redirect(url_for('student.classes'))
    
    class_instance = enrollment.class_instance
    course = class_instance.course
    professor = User.query.get(class_instance.professor_id)
    
    # Get all sessions
    sessions = ClassSession.query.filter_by(
        class_instance_id=class_id
    ).order_by(ClassSession.date).all()
    
    # Get student's attendance records for this class
    attendance_records = AttendanceRecord.query.filter(
        AttendanceRecord.student_id == current_user.id,
        AttendanceRecord.session_id.in_([s.id for s in sessions])
    ).all()
    
    attendance_map = {record.session_id: record for record in attendance_records}
    
    # Organize sessions
    past_sessions = []
    upcoming_sessions = []
    today = campus_today()
    
    for session in sessions:
        session_data = {
            'id': session.id,
            'session_number': session.session_number,
            'date': session.date,
            'start_time': session.start_time,
            'end_time': session.end_time,
            'room': session.room_location,
            'status': session.status,
            'is_active': session.is_active,
            'attendance': attendance_map.get(session.id)
        }
        
        if session.date < today:
            past_sessions.append(session_data)
        else:
            upcoming_sessions.append(session_data)
    
    # Calculate stats
    completed_sessions = [s for s in sessions if s.status == 'completed']
    attended = sum(
        1 for s in completed_sessions
        if attendance_map.get(s.id) and attendance_map[s.id].status in ['present', 'late', 'excused']
    )
    attendance_rate = round((attended / len(completed_sessions) * 100)) if completed_sessions else 0
    
    class_data = {
        'id': class_instance.id,
        'code': course.code,
        'name': course.name,
        'description': course.description,
        'credits': course.credits,
        'professor': professor.full_name if professor else 'Unknown',
        'professor_email': professor.email if professor else '',
        'room': class_instance.room_location,
        'schedule': f"{', '.join(class_instance.days_list)} {class_instance.start_time}-{class_instance.end_time}",
        'enrollment_date': enrollment.enrollment_date
    }
    
    stats = {
        'total_sessions': len(completed_sessions),
        'attended_sessions': attended,
        'attendance_rate': attendance_rate
    }
    
    return render_template('student/class_detail.html',
        class_data=class_data,
        stats=stats,
        past_sessions=past_sessions,
        upcoming_sessions=upcoming_sessions
    )


@student_bp.route('/scan')
@login_required
@student_required
def scan():
    """QR code scanning page"""
    student = Student.query.filter_by(user_id=current_user.id).first()
    
    # Check if QR data is in URL params (from scanning)
    qr_data = request.args.get('data')
    
    return render_template('student/scan.html', 
        student=student,
        qr_data=qr_data
    )


@student_bp.route('/scan/process', methods=['POST'])
@login_required
@student_required
def process_scan():
    """Process a QR scan through the shared attendance workflow."""
    try:
        data = request.get_json(silent=True) or {}
        qr_data = data.get('qr_data')
        if not qr_data:
            return jsonify({'success': False, 'error': 'No QR data provided'})
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

        student = Student.query.filter_by(user_id=current_user.id).first()
        socketio.emit('attendance_update', {
            'sessionId': result['session'].id,
            'studentId': current_user.id,
            'status': result['status'],
            'scanned_at': result['scanned_at'].isoformat(),
            'attendanceCount': result['attendance_count'],
            'newRecord': {
                'name': current_user.full_name,
                'student_id': student.student_id if student else current_user.email,
                'status': result['status'],
                'time': result['scanned_at'].strftime('%H:%M:%S')
            }
        }, room=f"session-{result['session'].id}")

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


@student_bp.route('/attendance')
@login_required
@student_required
def attendance():
    """Attendance history page"""
    student = Student.query.filter_by(user_id=current_user.id).first()
    
    # Get all attendance records
    records = db.session.query(AttendanceRecord, ClassSession, ClassInstance, Course).join(
        ClassSession, AttendanceRecord.session_id == ClassSession.id
    ).join(
        ClassInstance, ClassSession.class_instance_id == ClassInstance.id
    ).join(
        Course, ClassInstance.course_id == Course.id
    ).filter(
        AttendanceRecord.student_id == current_user.id
    ).order_by(AttendanceRecord.scanned_at.desc()).all()
    
    attendance_list = []
    for record, session, class_instance, course in records:
        professor = User.query.get(class_instance.professor_id)
        attendance_list.append({
            'id': record.id,
            'date': session.date,
            'time': record.scanned_at.strftime('%H:%M'),
            'status': record.status,
            'minutes_late': record.minutes_late,
            'class_code': course.code,
            'class_name': course.name,
            'professor': professor.full_name if professor else 'Unknown',
            'room': session.room_location
        })
    
    # Calculate overall stats
    total = len(attendance_list)
    present = sum(1 for a in attendance_list if a['status'] == 'present')
    late = sum(1 for a in attendance_list if a['status'] == 'late')
    absent = sum(1 for a in attendance_list if a['status'] == 'absent')
    excused = sum(1 for a in attendance_list if a['status'] == 'excused')
    
    stats = {
        'total': total,
        'present': present,
        'late': late,
        'absent': absent,
        'excused': excused,
        'attendance_rate': round(((present + late + excused) / total * 100)) if total > 0 else 0
    }

    appeals = {
        appeal.attendance_id: appeal
        for appeal in AttendanceAppeal.query.filter_by(student_id=current_user.id).all()
    }
    
    return render_template('student/attendance.html',
        attendance_list=attendance_list,
        stats=stats,
        appeals=appeals
    )


@student_bp.route('/attendance/<record_id>/appeal', methods=['POST'])
@login_required
@student_required
def submit_appeal(record_id):
    """Submit one review request for an absent or late attendance record."""
    record = AttendanceRecord.query.filter_by(id=record_id, student_id=current_user.id).first()
    if not record:
        flash('Attendance record not found.', 'error')
        return redirect(url_for('student.attendance'))
    if record.status not in ('absent', 'late'):
        flash('Only absent or late records can be appealed.', 'info')
        return redirect(url_for('student.attendance'))
    if AttendanceAppeal.query.filter_by(attendance_id=record.id).first():
        flash('A review request already exists for this record.', 'info')
        return redirect(url_for('student.attendance'))

    reason = request.form.get('reason', '').strip()
    if len(reason) < 10:
        flash('Please provide at least 10 characters explaining the request.', 'error')
        return redirect(url_for('student.attendance'))

    appeal = AttendanceAppeal(attendance_id=record.id, student_id=current_user.id, reason=reason)
    db.session.add(appeal)
    record_audit_event(current_user.id, 'attendance_appeal_submitted', 'attendance_record', record.id)
    db.session.commit()
    flash('Your attendance review request has been submitted.', 'success')
    return redirect(url_for('student.attendance'))


@student_bp.route('/profile')
@login_required
@student_required
def profile():
    """Student profile page"""
    student = Student.query.filter_by(user_id=current_user.id).first()
    return render_template('student/profile.html', student=student)


@student_bp.route('/devices')
@login_required
@student_required
def devices():
    registrations = DeviceRegistration.query.filter_by(user_id=current_user.id).order_by(
        DeviceRegistration.last_seen_at.desc()
    ).all()
    return render_template('student/devices.html', devices=registrations,
                           max_devices=current_app.config.get('MAX_REGISTERED_DEVICES', 2))


@student_bp.route('/devices/<device_id>/revoke', methods=['POST'])
@login_required
@student_required
def revoke_device(device_id):
    device = DeviceRegistration.query.filter_by(id=device_id, user_id=current_user.id).first()
    if not device:
        flash('Device not found.', 'error')
        return redirect(url_for('student.devices'))
    device.is_active = False
    record_audit_event(current_user.id, 'device_revoked', 'device_registration', device.id,
                       ip_address=request.remote_addr)
    db.session.commit()
    flash('Device access revoked. You can register a replacement at the next scan.', 'success')
    return redirect(url_for('student.devices'))


@student_bp.route('/profile/update', methods=['POST'])
@login_required
@student_required
def update_profile():
    """Update student profile"""
    try:
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        phone = request.form.get('phone', '').strip()
        major = request.form.get('major', '').strip()
        
        if first_name:
            current_user.first_name = first_name
        if last_name:
            current_user.last_name = last_name
        if phone:
            current_user.phone = phone
        
        student = Student.query.filter_by(user_id=current_user.id).first()
        if student and major:
            student.major = major
        
        db.session.commit()
        flash('Profile updated successfully.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating profile: {str(e)}', 'error')
    
    return redirect(url_for('student.profile'))
