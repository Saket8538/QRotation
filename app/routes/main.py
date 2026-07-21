"""
Main routes for home and common pages
"""
from flask import Blueprint, render_template, redirect, url_for
from flask_login import current_user

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    """Home page"""
    if current_user.is_authenticated:
        if current_user.role == 'student':
            return redirect(url_for('student.dashboard'))
        if current_user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        else:
            return redirect(url_for('professor.dashboard'))
    return render_template('main/index.html')


@main_bp.route('/about')
def about():
    """About page"""
    return render_template('main/about.html')


@main_bp.route('/health')
def health():
    """Health check endpoint"""
    return {
        'status': 'OK',
        'message': 'QRotation is running',
        'features': [
            'QR Code Generation',
            'Dynamic QR Rotation',
            'Real-time Attendance Tracking',
            'Student/Professor Dashboards',
            'Session Management',
            'Enrollment Management',
            'Attendance Analytics',
            'Offline-first PWA',
            'Device-bound anti-fraud signals',
            'Explainable attendance Copilot',
            'Student success interventions',
            'Immutable audit history'
        ]
    }
