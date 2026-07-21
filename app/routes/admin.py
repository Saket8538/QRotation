"""Institution administrator views and governance APIs."""
from functools import wraps

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from app import db
from app.models import (
    AttendanceAppeal, AuditLog, ClassInstance, ClassSession, Enrollment,
    FraudAlert, User
)

admin_bp = Blueprint('admin', __name__)


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            return jsonify({'success': False, 'error': 'Administrator access required'}), 403
        return view(*args, **kwargs)
    return wrapped


@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    counts = {
        'students': User.query.filter_by(role='student', is_active=True).count(),
        'professors': User.query.filter_by(role='professor', is_active=True).count(),
        'classes': ClassInstance.query.filter_by(is_active=True).count(),
        'sessions': ClassSession.query.count(),
        'enrollments': Enrollment.query.filter_by(status='active').count(),
        'open_fraud_alerts': FraudAlert.query.filter_by(status='open').count(),
        'pending_appeals': AttendanceAppeal.query.filter_by(status='pending').count(),
    }
    recent_audit = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(25).all()
    return render_template('admin/dashboard.html', counts=counts, recent_audit=recent_audit)


@admin_bp.route('/api/audit')
@login_required
@admin_required
def audit_api():
    limit = min(max(request.args.get('limit', 100, type=int), 1), 500)
    entries = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return jsonify({'success': True, 'audit': [{
        'id': entry.id,
        'actor_id': entry.actor_id,
        'action': entry.action,
        'entity_type': entry.entity_type,
        'entity_id': entry.entity_id,
        'details': entry.details,
        'ip_address': entry.ip_address,
        'created_at': entry.created_at.isoformat() if entry.created_at else None
    } for entry in entries]})

