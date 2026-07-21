from flask import request
from flask_login import current_user
from flask_socketio import join_room, leave_room
from app import socketio


def _can_join_session_room(session_id):
    """Allow only the owning professor or an enrolled student into a live room."""
    from app.models import ClassSession, Enrollment

    session = ClassSession.query.get(session_id)
    if not session:
        return False
    if current_user.role == 'professor':
        return session.class_instance.professor_id == current_user.id
    if current_user.role == 'student':
        return Enrollment.query.filter_by(
            student_id=current_user.id,
            class_instance_id=session.class_instance_id,
            status='active'
        ).first() is not None
    return False

@socketio.on('join')
def on_join(data):
    """Join a room"""
    room = (data or {}).get('room', '')
    if room.startswith('session-') and _can_join_session_room(room[len('session-'):]):
        join_room(room)

@socketio.on('leave')
def on_leave(data):
    """Leave a room"""
    room = (data or {}).get('room', '')
    if room.startswith('session-'):
        leave_room(room)

@socketio.on('connect')
def on_connect():
    if not current_user.is_authenticated:
        return False
    join_room(f'user-{current_user.id}')

@socketio.on('disconnect')
def on_disconnect():
    pass
