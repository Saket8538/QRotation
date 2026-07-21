"""
Session generator utility for creating class sessions
"""
from datetime import timedelta
import json
import uuid


def generate_sessions_for_class(class_instance):
    """
    Generate session templates for a class instance
    
    Args:
        class_instance: ClassInstance model object
        
    Returns:
        list: List of ClassSession objects
    """
    from app import db
    from app.models import ClassSession
    
    sessions = []
    
    # Parse days of week
    try:
        days_of_week = json.loads(class_instance.days_of_week) if isinstance(class_instance.days_of_week, str) else class_instance.days_of_week
    except (json.JSONDecodeError, TypeError):
        days_of_week = []
    
    # Map day names to weekday numbers (Monday=0, Sunday=6)
    day_map = {
        'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 
        'Thursday': 3, 'Friday': 4, 'Saturday': 5, 'Sunday': 6
    }
    
    target_days = sorted({day_map[day] for day in days_of_week if day in day_map})
    
    if not target_days:
        return sessions
    
    current_date = class_instance.first_class_date
    end_date = class_instance.last_class_date
    if not current_date or not end_date or current_date > end_date:
        return sessions
    session_number = 1
    
    while current_date <= end_date:
        if current_date.weekday() in target_days:
            session = ClassSession(
                id=str(uuid.uuid4()),
                class_instance_id=class_instance.id,
                session_number=session_number,
                date=current_date,
                start_time=class_instance.start_time,
                end_time=class_instance.end_time,
                room_location=class_instance.room_location,
                status='scheduled',
                is_active=False,
                total_enrolled=0,
                attendance_count=0
            )
            sessions.append(session)
            session_number += 1
        
        current_date += timedelta(days=1)
    
    # Add sessions to database
    for session in sessions:
        db.session.add(session)
    
    db.session.commit()
    
    return sessions
