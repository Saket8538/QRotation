"""
Reports and Export Utilities
Generate attendance reports in various formats
"""
import pandas as pd
from datetime import datetime, date
from io import BytesIO
from flask import make_response
from app.models import (
    User, Student, ClassInstance, ClassSession, 
    AttendanceRecord, Enrollment, Course, SessionRoster
)
from app import db


def generate_attendance_report_data(class_id=None, start_date=None, end_date=None, student_id=None):
    """
    Generate attendance report data with filters
    """
    query = db.session.query(
        AttendanceRecord,
        ClassSession,
        ClassInstance,
        Course,
        User
    ).join(
        ClassSession, AttendanceRecord.session_id == ClassSession.id
    ).join(
        ClassInstance, ClassSession.class_instance_id == ClassInstance.id
    ).join(
        Course, ClassInstance.course_id == Course.id
    ).join(
        User, AttendanceRecord.student_id == User.id
    )
    
    # Apply filters
    if class_id:
        query = query.filter(ClassInstance.id == class_id)
    
    if start_date:
        query = query.filter(ClassSession.date >= start_date)
    
    if end_date:
        query = query.filter(ClassSession.date <= end_date)
    
    if student_id:
        query = query.filter(AttendanceRecord.student_id == student_id)
    
    results = query.order_by(ClassSession.date.desc()).all()
    
    # Format data
    data = []
    for record, session, class_inst, course, user in results:
        data.append({
            'Date': session.date.strftime('%Y-%m-%d'),
            'Course Code': course.code,
            'Course Name': course.name,
            'Session Number': session.session_number,
            'Student ID': user.student_profile.student_id if user.student_profile else 'N/A',
            'Student Name': user.full_name,
            'Student Email': user.email,
            'Status': record.status.title(),
            'Scanned At': record.scanned_at.strftime('%Y-%m-%d %H:%M:%S') if record.scanned_at else 'N/A',
            'Minutes Late': record.minutes_late if record.minutes_late else 0,
            'Location Verified': 'Yes' if record.location_verified else 'No',
            'Distance (m)': round(record.location_distance, 2) if record.location_distance else 'N/A',
            'Room': session.room_location,
            'Session Time': f"{session.start_time} - {session.end_time}"
        })
    
    return data


def export_to_excel(data, filename='attendance_report.xlsx'):
    """
    Export data to Excel format
    """
    df = pd.DataFrame(data)
    
    # Create Excel writer
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Attendance', index=False)
        
        # Get workbook and worksheet
        workbook = writer.book
        worksheet = writer.sheets['Attendance']
        
        # Auto-adjust column widths
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            worksheet.column_dimensions[column_letter].width = adjusted_width
    
    output.seek(0)
    
    # Create response
    response = make_response(output.read())
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    
    return response


def export_to_csv(data, filename='attendance_report.csv'):
    """
    Export data to CSV format
    """
    df = pd.DataFrame(data)
    
    # Create CSV
    output = BytesIO()
    df.to_csv(output, index=False, encoding='utf-8')
    output.seek(0)
    
    # Create response
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    
    return response


def generate_class_summary(class_id):
    """
    Generate summary statistics for a class
    """
    class_instance = ClassInstance.query.get(class_id)
    if not class_instance:
        return None
    
    # Get all sessions
    sessions = ClassSession.query.filter_by(
        class_instance_id=class_id,
        status='completed'
    ).all()
    
    total_sessions = len(sessions)
    session_ids = [session.id for session in sessions]
    roster_by_student = {}
    if session_ids:
        for entry in SessionRoster.query.filter(SessionRoster.session_id.in_(session_ids)).all():
            roster_by_student.setdefault(entry.student_id, set()).add(entry.session_id)

    # Completed sessions created before roster snapshots are supported with the
    # previous active-enrollment behavior, without affecting newer snapshots.
    rostered_session_ids = {session_id for roster in roster_by_student.values() for session_id in roster}
    legacy_session_ids = set(session_ids) - rostered_session_ids
    if legacy_session_ids:
        for enrollment in Enrollment.query.filter_by(class_instance_id=class_id, status='active').all():
            roster_by_student.setdefault(enrollment.student_id, set()).update(legacy_session_ids)

    attendance_data = []
    for student_id, eligible_session_ids in roster_by_student.items():
        student = db.session.get(User, student_id)
        if not student:
            continue

        present_count = AttendanceRecord.query.filter(
            AttendanceRecord.student_id == student_id,
            AttendanceRecord.session_id.in_(eligible_session_ids),
            AttendanceRecord.status.in_(['present', 'late', 'excused'])
        ).count()
        late_count = AttendanceRecord.query.filter(
            AttendanceRecord.student_id == student_id,
            AttendanceRecord.session_id.in_(eligible_session_ids),
            AttendanceRecord.status == 'late'
        ).count()
        eligible_session_count = len(eligible_session_ids)
        attendance_rate = (present_count / eligible_session_count * 100) if eligible_session_count else 0

        attendance_data.append({
            'student_id': student.student_profile.student_id if student.student_profile else 'N/A',
            'student_name': student.full_name,
            'email': student.email,
            'present_count': present_count,
            'late_count': late_count,
            'absent_count': eligible_session_count - present_count,
            'attendance_rate': round(attendance_rate, 2)
        })
    
    return {
        'class_code': class_instance.class_code,
        'course': class_instance.course,
        'total_sessions': total_sessions,
        'total_students': len(attendance_data),
        'attendance_data': attendance_data,
        'average_attendance': round(sum(d['attendance_rate'] for d in attendance_data) / len(attendance_data), 2) if attendance_data else 0
    }


def get_low_attendance_students(class_id, threshold=75):
    """
    Get students with attendance below threshold
    """
    summary = generate_class_summary(class_id)
    if not summary:
        return []
    
    low_attendance = [
        student for student in summary['attendance_data']
        if student['attendance_rate'] < threshold
    ]
    
    return low_attendance


def generate_student_attendance_report(student_id, start_date=None, end_date=None):
    """
    Generate attendance report for a specific student
    """
    user = User.query.get(student_id)
    if not user or user.role != 'student':
        return None
    
    # Get all attendance records
    query = db.session.query(
        AttendanceRecord,
        ClassSession,
        ClassInstance,
        Course
    ).join(
        ClassSession, AttendanceRecord.session_id == ClassSession.id
    ).join(
        ClassInstance, ClassSession.class_instance_id == ClassInstance.id
    ).join(
        Course, ClassInstance.course_id == Course.id
    ).filter(
        AttendanceRecord.student_id == student_id
    )
    
    if start_date:
        query = query.filter(ClassSession.date >= start_date)
    
    if end_date:
        query = query.filter(ClassSession.date <= end_date)
    
    results = query.order_by(ClassSession.date.desc()).all()
    
    # Calculate statistics by class
    class_stats = {}
    for record, session, class_inst, course in results:
        class_key = class_inst.id
        
        if class_key not in class_stats:
            class_stats[class_key] = {
                'course_code': course.code,
                'course_name': course.name,
                'class_code': class_inst.class_code,
                'present': 0,
                'late': 0,
                'absent': 0,
                'total': 0
            }
        
        class_stats[class_key]['total'] += 1
        
        if record.status in ['present', 'excused']:
            class_stats[class_key]['present'] += 1
        elif record.status == 'late':
            class_stats[class_key]['late'] += 1
        else:
            class_stats[class_key]['absent'] += 1
    
    # Calculate attendance rates
    for class_key in class_stats:
        stats = class_stats[class_key]
        attended = stats['present'] + stats['late']
        stats['attendance_rate'] = round((attended / stats['total'] * 100), 2) if stats['total'] > 0 else 0
    
    return {
        'student': user,
        'class_statistics': list(class_stats.values()),
        'total_classes_enrolled': len(class_stats),
        'overall_attendance_rate': round(
            sum(s['attendance_rate'] for s in class_stats.values()) / len(class_stats),
            2
        ) if class_stats else 0
    }
