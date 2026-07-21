"""
Authentication routes for login, register, password reset
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import User, Student, Professor
from config import Config
import uuid
from urllib.parse import urljoin, urlparse

auth_bp = Blueprint('auth', __name__)


def _safe_next_url(target):
    """Allow only same-origin redirects after login."""
    if not target:
        return None
    ref = urlparse(request.host_url)
    candidate = urlparse(urljoin(request.host_url, target))
    if candidate.scheme in ('http', 'https') and candidate.netloc == ref.netloc:
        return candidate.path + (f'?{candidate.query}' if candidate.query else '')
    return None


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Login page for both students and professors"""
    if current_user.is_authenticated:
        if current_user.role == 'student':
            return redirect(url_for('student.dashboard'))
        if current_user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        else:
            return redirect(url_for('professor.dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        role = request.form.get('role', 'student')
        
        if not email or not password:
            flash('Please enter both email and password.', 'error')
            return render_template('auth/login.html')
        
        user = User.query.filter_by(email=email).first()
        
        if not user or not user.check_password(password):
            flash('Invalid email or password.', 'error')
            return render_template('auth/login.html')
        
        if user.role != role:
            flash(f'This account is not registered as a {role}.', 'error')
            return render_template('auth/login.html')
        
        login_user(user, remember=True)
        flash(f'Welcome back, {user.first_name}!', 'success')
        
        next_page = _safe_next_url(request.args.get('next'))
        if next_page:
            return redirect(next_page)
        
        if user.role == 'student':
            return redirect(url_for('student.dashboard'))
        if user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        else:
            return redirect(url_for('professor.dashboard'))
    
    return render_template('auth/login.html')


@auth_bp.route('/student/login', methods=['GET', 'POST'])
def student_login():
    """Student-specific login page"""
    if current_user.is_authenticated:
        return redirect(url_for('student.dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        if not email or not password:
            flash('Please enter both email and password.', 'error')
            return render_template('auth/student_login.html')
        
        user = User.query.filter_by(email=email, role='student').first()
        
        if not user or not user.check_password(password):
            flash('Invalid email or password.', 'error')
            return render_template('auth/student_login.html')
        
        login_user(user, remember=True)
        flash(f'Welcome back, {user.first_name}!', 'success')
        
        next_page = _safe_next_url(request.args.get('next'))
        if next_page:
            return redirect(next_page)
        
        return redirect(url_for('student.dashboard'))
    
    return render_template('auth/student_login.html')


@auth_bp.route('/professor/login', methods=['GET', 'POST'])
def professor_login():
    """Professor-specific login page"""
    if current_user.is_authenticated:
        return redirect(url_for('professor.dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        if not email or not password:
            flash('Please enter both email and password.', 'error')
            return render_template('auth/professor_login.html')
        
        user = User.query.filter_by(email=email, role='professor').first()
        
        if not user or not user.check_password(password):
            flash('Invalid email or password.', 'error')
            return render_template('auth/professor_login.html')
        
        login_user(user, remember=True)
        flash(f'Welcome back, {user.first_name}!', 'success')
        
        next_page = _safe_next_url(request.args.get('next'))
        if next_page:
            return redirect(next_page)
        
        return redirect(url_for('professor.dashboard'))
    
    return render_template('auth/professor_login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """General registration page"""
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    return render_template('auth/register.html')


@auth_bp.route('/student/register', methods=['GET', 'POST'])
def student_register():
    """Student registration page"""
    if current_user.is_authenticated:
        return redirect(url_for('student.dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        student_id = request.form.get('student_id', '').strip()
        major = request.form.get('major', 'Undeclared').strip()
        
        # Validate email domain
        if not email.endswith(Config.ALLOWED_EMAIL_DOMAIN):
            flash(f'Only {Config.ALLOWED_EMAIL_DOMAIN} emails are allowed.', 'error')
            return render_template('auth/student_register.html')
        
        # Validate required fields
        if not all([email, password, first_name, last_name, student_id]):
            flash('Please fill in all required fields.', 'error')
            return render_template('auth/student_register.html')
        
        # Validate password match
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('auth/student_register.html')
        
        # Check if email exists
        if User.query.filter_by(email=email).first():
            flash('An account with this email already exists.', 'error')
            return render_template('auth/student_register.html')
        
        # Check if student ID exists
        if Student.query.filter_by(student_id=student_id).first():
            flash('This student ID is already registered.', 'error')
            return render_template('auth/student_register.html')
        
        try:
            # Create user
            user_id = str(uuid.uuid4())
            user = User(
                id=user_id,
                email=email,
                first_name=first_name,
                last_name=last_name,
                role='student'
            )
            user.set_password(password)
            db.session.add(user)
            
            # Create student profile
            student = Student(
                user_id=user_id,
                student_id=student_id,
                major=major
            )
            db.session.add(student)
            
            db.session.commit()
            
            login_user(user, remember=True)
            flash('Registration successful! Welcome to the QRotation.', 'success')
            return redirect(url_for('student.dashboard'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Registration failed: {str(e)}', 'error')
            return render_template('auth/student_register.html')
    
    return render_template('auth/student_register.html')


@auth_bp.route('/professor/register', methods=['GET', 'POST'])
def professor_register():
    """Professor registration page"""
    if current_user.is_authenticated:
        return redirect(url_for('professor.dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        employee_id = request.form.get('employee_id', '').strip()
        title = request.form.get('title', 'Professor').strip()
        
        # Validate email domain
        if not email.endswith(Config.ALLOWED_EMAIL_DOMAIN):
            flash(f'Only {Config.ALLOWED_EMAIL_DOMAIN} emails are allowed.', 'error')
            return render_template('auth/professor_register.html')
        
        # Validate required fields
        if not all([email, password, first_name, last_name, employee_id]):
            flash('Please fill in all required fields.', 'error')
            return render_template('auth/professor_register.html')
        
        # Validate password match
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('auth/professor_register.html')
        
        # Check if email exists
        if User.query.filter_by(email=email).first():
            flash('An account with this email already exists.', 'error')
            return render_template('auth/professor_register.html')
        
        # Check if employee ID exists
        if Professor.query.filter_by(employee_id=employee_id).first():
            flash('This employee ID is already registered.', 'error')
            return render_template('auth/professor_register.html')
        
        try:
            # Create user
            user_id = str(uuid.uuid4())
            user = User(
                id=user_id,
                email=email,
                first_name=first_name,
                last_name=last_name,
                role='professor'
            )
            user.set_password(password)
            db.session.add(user)
            
            # Create professor profile
            professor = Professor(
                user_id=user_id,
                employee_id=employee_id,
                title=title
            )
            db.session.add(professor)
            
            db.session.commit()
            
            login_user(user, remember=True)
            flash('Registration successful! Welcome to the QRotation.', 'success')
            return redirect(url_for('professor.dashboard'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Registration failed: {str(e)}', 'error')
            return render_template('auth/professor_register.html')
    
    return render_template('auth/professor_register.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """Logout user"""
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.index'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Password reset request page"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        
        user = User.query.filter_by(email=email).first()
        
        # Always show success message to prevent email enumeration
        flash('If an account exists with this email, you will receive password reset instructions.', 'info')
        
        if user:
            # In a real system, you would send an email here
            # For this demo, we'll just show a message
            pass
        
        return redirect(url_for('auth.login'))
    
    return render_template('auth/forgot_password.html')
