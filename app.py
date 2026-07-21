"""
QRotation with real-time sync and QR rotation
Python Flask Application - Main entry point to run the application
"""

import os
import sys

# Add the project directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db, socketio
from app.models import (
    User, Student, Professor, Department, AcademicPeriod, 
    Course, ClassInstance, ClassSession, Enrollment, AttendanceRecord
)
from app.utils.seed_data import seed_initial_data


def init_database(app):
    """Initialize the database with tables and seed data"""
    with app.app_context():
        # Create all tables
        db.create_all()
        print("✓ Database tables created")
        
        # Check if seed data exists
        if Department.query.count() == 0:
            seed_initial_data()
            print("✓ Seed data inserted")
        else:
            print("✓ Seed data already exists")


def create_test_users(app):
    """Create test users for development"""
    with app.app_context():
        # Check if test users exist
        if User.query.filter_by(email='professor@acem.ac.in').first():
            print("✓ Test users already exist")
            return
        
        from werkzeug.security import generate_password_hash
        
        # Create a test professor
        prof_user = User(
            email='professor@acem.ac.in',
            password_hash=generate_password_hash('password123'),
            first_name='John',
            last_name='Smith',
            role='professor',
            is_active=True
        )
        db.session.add(prof_user)
        db.session.flush()
        
        dept = Department.query.first()
        professor = Professor(
            user_id=prof_user.id,
            employee_id='EMP001',
            department_id=dept.id if dept else None,
            title='Prof.'
        )
        db.session.add(professor)
        
        # Create a test student
        student_user = User(
            email='student@acem.ac.in',
            password_hash=generate_password_hash('password123'),
            first_name='Jane',
            last_name='Doe',
            role='student',
            is_active=True
        )
        db.session.add(student_user)
        db.session.flush()
        
        student = Student(
            user_id=student_user.id,
            student_id='STU001',
            major='Computer Science',
            enrollment_year=2024
        )
        db.session.add(student)
        
        db.session.commit()
        print("✓ Test users created:")
        print("  Professor: professor@acem.ac.in / password123")
        print("  Student: student@acem.ac.in / password123")


def create_test_class(app):
    """Create a test class with enrollment for demonstration"""
    with app.app_context():
        # Check if test class exists
        if ClassInstance.query.count() > 0:
            print("✓ Test class already exists")
            return
        
        professor = Professor.query.first()
        student = Student.query.first()
        course = Course.query.first()
        period = AcademicPeriod.query.filter_by(is_current=True).first()
        
        if not all([professor, student, course, period]):
            print("! Cannot create test class - missing data")
            return
        
        from datetime import date, timedelta
        import json
        import random
        import string
        
        today = date.today()
        
        # Generate unique class code
        class_code = f"{course.code}-{''.join(random.choices(string.ascii_uppercase, k=6))}"
        
        # Create a class instance
        class_instance = ClassInstance(
            course_id=course.id,
            professor_id=professor.user_id,
            academic_period_id=period.id,
            section_number=1,
            class_code=class_code,
            days_of_week=json.dumps(['Monday', 'Wednesday', 'Friday']),
            start_time='09:00',
            end_time='10:00',
            first_class_date=today - timedelta(days=30),
            last_class_date=today + timedelta(days=60),
            room_location='Room 101',
            max_students=50,
            is_active=True
        )
        db.session.add(class_instance)
        db.session.flush()
        
        # Enroll the student
        enrollment = Enrollment(
            student_id=student.user_id,
            class_instance_id=class_instance.id,
            status='active'
        )
        db.session.add(enrollment)
        
        # Create a few sessions
        for i in range(5):
            session_date = today - timedelta(days=i*2)
            session = ClassSession(
                class_instance_id=class_instance.id,
                session_number=5-i,
                date=session_date,
                start_time='09:00',
                end_time='10:00',
                status='completed' if i > 0 else 'scheduled'
            )
            db.session.add(session)
        
        db.session.commit()
        print("✓ Test class created with enrollment and sessions")


def main():
    """Main entry point"""
    print("\n" + "="*50)
    print("QRotation - Python Flask")
    print("="*50 + "\n")
    
    # Create the Flask application
    app = create_app()
    
    # Initialize database
    print("Initializing database...")
    init_database(app)
    
    # Create test users (for development)
    print("\nSetting up test data...")
    create_test_users(app)
    create_test_class(app)
    
    # Run the application
    print("\n" + "-"*50)
    print("Starting server...")
    print("-"*50)
    
    port = int(os.environ.get('PORT', 5000))
    
    print(f"\n🚀 Server running at: http://localhost:{port}")
    print(f"📱 QR Scan URL: http://localhost:{port}/student/scan")
    print("\nTest Credentials:")
    print("  Professor: professor@acem.ac.in / password123")
    print("  Student: student@acem.ac.in / password123")
    print("\nPress Ctrl+C to stop the server\n")
    
    # Run with SocketIO for real-time features
    socketio.run(
        app,
        host='0.0.0.0',
        port=port,
        debug=True,
        use_reloader=False,  # Disable auto-restart to prevent port conflicts
        allow_unsafe_werkzeug=True
    )


if __name__ == '__main__':
    main()
