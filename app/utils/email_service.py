"""
Email Notification System
Send automated emails for attendance alerts and reminders
"""
from flask import current_app, render_template_string
from flask_mail import Mail, Message
from threading import Thread
from datetime import datetime, date, timedelta
from app.models import (
    User, Student, Professor, ClassInstance, ClassSession,
    AttendanceRecord, Enrollment
)
from app import db

mail = Mail()


def send_async_email(app, msg):
    """Send email asynchronously"""
    with app.app_context():
        try:
            mail.send(msg)
        except Exception as e:
            print(f"Failed to send email: {e}")


def send_email(subject, recipients, html_body, text_body=None):
    """Send email"""
    app = current_app._get_current_object()
    
    msg = Message(
        subject=subject,
        sender=current_app.config.get('MAIL_DEFAULT_SENDER', 'noreply@attendance.com'),
        recipients=recipients if isinstance(recipients, list) else [recipients]
    )
    
    msg.html = html_body
    if text_body:
        msg.body = text_body
    
    # Send asynchronously
    Thread(target=send_async_email, args=(app, msg)).start()


def send_low_attendance_alert(student_email, student_name, class_code, course_name, attendance_rate):
    """Send low attendance alert to student"""
    subject = f"⚠️ Low Attendance Alert - {course_name}"
    
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px;">
        <h2 style="color: #dc2626;">Low Attendance Alert</h2>
        <p>Dear {student_name},</p>
        <p>This is to inform you that your attendance in <strong>{course_name} ({class_code})</strong> 
        has fallen below the required threshold.</p>
        
        <div style="background-color: #fef2f2; padding: 15px; border-left: 4px solid #dc2626; margin: 20px 0;">
            <p style="margin: 0;"><strong>Current Attendance Rate:</strong> {attendance_rate}%</p>
            <p style="margin: 5px 0;"><strong>Required Minimum:</strong> 75%</p>
        </div>
        
        <p>Please ensure regular attendance to meet the course requirements.</p>
        
        <p style="margin-top: 30px;">
            Best regards,<br>
            QRotation
        </p>
    </body>
    </html>
    """
    
    text_body = f"""
    Low Attendance Alert
    
    Dear {student_name},
    
    Your attendance in {course_name} ({class_code}) has fallen below the required threshold.
    
    Current Attendance Rate: {attendance_rate}%
    Required Minimum: 75%
    
    Please ensure regular attendance to meet the course requirements.
    
    Best regards,
    QRotation
    """
    
    send_email(subject, student_email, html_body, text_body)


def send_session_reminder(student_email, student_name, course_name, class_code, session_date, session_time, room):
    """Send session reminder to student"""
    subject = f"📅 Class Reminder - {course_name}"
    
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px;">
        <h2 style="color: #2563eb;">Class Session Reminder</h2>
        <p>Dear {student_name},</p>
        <p>This is a reminder for your upcoming class session:</p>
        
        <div style="background-color: #eff6ff; padding: 15px; border-left: 4px solid #2563eb; margin: 20px 0;">
            <p style="margin: 0;"><strong>Course:</strong> {course_name} ({class_code})</p>
            <p style="margin: 5px 0;"><strong>Date:</strong> {session_date}</p>
            <p style="margin: 5px 0;"><strong>Time:</strong> {session_time}</p>
            <p style="margin: 5px 0;"><strong>Room:</strong> {room}</p>
        </div>
        
        <p>Please ensure you attend and mark your attendance using the QR code.</p>
        
        <p style="margin-top: 30px;">
            Best regards,<br>
            QRotation
        </p>
    </body>
    </html>
    """
    
    text_body = f"""
    Class Session Reminder
    
    Dear {student_name},
    
    Course: {course_name} ({class_code})
    Date: {session_date}
    Time: {session_time}
    Room: {room}
    
    Please ensure you attend and mark your attendance.
    
    Best regards,
    QRotation
    """
    
    send_email(subject, student_email, html_body, text_body)


def send_professor_daily_summary(professor_email, professor_name, classes_today, total_present, total_absent):
    """Send daily attendance summary to professor"""
    subject = f"📊 Daily Attendance Summary - {date.today().strftime('%B %d, %Y')}"
    
    classes_html = ""
    for cls in classes_today:
        classes_html += f"""
        <li style="margin: 10px 0;">
            <strong>{cls['course_name']} ({cls['class_code']})</strong><br>
            Time: {cls['time']} | Room: {cls['room']}<br>
            Present: {cls['present']} | Absent: {cls['absent']} | Attendance Rate: {cls['rate']}%
        </li>
        """
    
    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px;">
        <h2 style="color: #2563eb;">Daily Attendance Summary</h2>
        <p>Dear Prof. {professor_name},</p>
        <p>Here's your attendance summary for today ({date.today().strftime('%B %d, %Y')}):</p>
        
        <div style="background-color: #f9fafb; padding: 15px; border-radius: 8px; margin: 20px 0;">
            <h3>Overall Statistics</h3>
            <p><strong>Total Sessions:</strong> {len(classes_today)}</p>
            <p><strong>Total Students Present:</strong> {total_present}</p>
            <p><strong>Total Students Absent:</strong> {total_absent}</p>
        </div>
        
        <h3>Class Details:</h3>
        <ul style="list-style: none; padding: 0;">
            {classes_html}
        </ul>
        
        <p style="margin-top: 30px;">
            Best regards,<br>
            QRotation
        </p>
    </body>
    </html>
    """
    
    send_email(subject, professor_email, html_body)


def check_and_send_low_attendance_alerts():
    """
    Check all students and send alerts for low attendance
    Should be run daily via cron job or scheduler
    """
    threshold = 75
    
    # Get all active enrollments
    enrollments = Enrollment.query.filter_by(status='active').all()
    
    for enrollment in enrollments:
        class_instance = enrollment.class_instance
        student = User.query.get(enrollment.student_id)
        
        if not student or not class_instance:
            continue
        
        # Calculate attendance rate
        total_sessions = ClassSession.query.filter_by(
            class_instance_id=class_instance.id,
            status='completed'
        ).count()
        
        if total_sessions == 0:
            continue
        
        attended = db.session.query(AttendanceRecord).join(ClassSession).filter(
            ClassSession.class_instance_id == class_instance.id,
            AttendanceRecord.student_id == student.id,
            AttendanceRecord.status.in_(['present', 'late', 'excused'])
        ).count()
        
        attendance_rate = round((attended / total_sessions * 100), 2)
        
        # Send alert if below threshold
        if attendance_rate < threshold:
            send_low_attendance_alert(
                student.email,
                student.full_name,
                class_instance.class_code,
                class_instance.course.name,
                attendance_rate
            )


def send_tomorrow_class_reminders():
    """
    Send reminders for tomorrow's classes
    Should be run daily at evening
    """
    tomorrow = date.today() + timedelta(days=1)
    tomorrow_day = tomorrow.strftime('%A')
    
    # Get all active class instances that meet tomorrow
    class_instances = ClassInstance.query.filter_by(is_active=True).all()
    
    for class_instance in class_instances:
        # Check if class meets tomorrow
        if tomorrow_day not in class_instance.days_list:
            continue
        
        # Get all enrolled students
        enrollments = Enrollment.query.filter_by(
            class_instance_id=class_instance.id,
            status='active'
        ).all()
        
        for enrollment in enrollments:
            student = User.query.get(enrollment.student_id)
            if not student:
                continue
            
            send_session_reminder(
                student.email,
                student.full_name,
                class_instance.course.name,
                class_instance.class_code,
                tomorrow.strftime('%B %d, %Y'),
                f"{class_instance.start_time} - {class_instance.end_time}",
                class_instance.room_location
            )
