"""Seed and reconcile local catalog data."""
from datetime import date, datetime


def _ensure_academic_periods(db, AcademicPeriod, current_year):
    """Create/update the default Spring, Summer, and Fall calendar idempotently."""
    specifications = [
        {
            'id': 'period-1',
            'name': f'Spring {current_year}',
            'semester': 'spring',
            'start_date': date(current_year, 1, 15),
            'end_date': date(current_year, 5, 31),
        },
        {
            'id': 'period-summer',
            'name': f'Summer {current_year}',
            'semester': 'summer',
            'start_date': date(current_year, 6, 1),
            'end_date': date(current_year, 7, 31),
        },
        {
            'id': 'period-2',
            'name': f'Fall {current_year}',
            'semester': 'fall',
            'start_date': date(current_year, 8, 1),
            'end_date': date(current_year, 12, 15),
        },
    ]
    today = date.today()
    AcademicPeriod.query.update({'is_current': False}, synchronize_session=False)
    for specification in specifications:
        period = AcademicPeriod.query.filter_by(
            year=current_year, semester=specification['semester']
        ).first()
        legacy_period = AcademicPeriod.query.filter_by(id=specification['id']).first()
        if not period and legacy_period and legacy_period.year == current_year:
            period = legacy_period
        if not period:
            period = AcademicPeriod(id=f"period-{current_year}-{specification['semester']}")
            db.session.add(period)
        period.name = specification['name']
        period.year = current_year
        period.semester = specification['semester']
        period.start_date = specification['start_date']
        period.end_date = specification['end_date']
        period.is_active = True
        period.is_current = specification['start_date'] <= today <= specification['end_date']


def seed_initial_data():
    """Seed the local catalog and reconcile academic periods on every startup."""
    from app import db
    from app.models import AcademicPeriod, Course, Department

    current_year = datetime.now().year
    if not Department.query.first():
        db.session.add_all([
            Department(id='dept-1', code='CSC', name='Computer Science'),
            Department(id='dept-2', code='MAT', name='Mathematics'),
            Department(id='dept-3', code='PHY', name='Physics'),
            Department(id='dept-4', code='ENG', name='English'),
            Department(id='dept-5', code='ECE', name='Electronics & Communication'),
        ])
        db.session.add_all([
            Course(id='course-1', code='CSC-101', name='Introduction to Computer Science', description='Fundamentals of computing and programming', credits=3, department_id='dept-1'),
            Course(id='course-2', code='CSC-201', name='Data Structures', description='Study of data organization and algorithms', credits=4, department_id='dept-1'),
            Course(id='course-3', code='CSC-301', name='Database Systems', description='Design and implementation of database systems', credits=3, department_id='dept-1'),
            Course(id='course-4', code='MAT-101', name='Calculus I', description='Differential and integral calculus', credits=4, department_id='dept-2'),
            Course(id='course-5', code='MAT-201', name='Linear Algebra', description='Vector spaces and linear transformations', credits=3, department_id='dept-2'),
            Course(id='course-6', code='PHY-101', name='Physics I', description='Mechanics and thermodynamics', credits=4, department_id='dept-3'),
            Course(id='course-7', code='ECE-101', name='Basic Electronics', description='Introduction to electronic circuits', credits=3, department_id='dept-5'),
        ])

    _ensure_academic_periods(db, AcademicPeriod, current_year)
    db.session.commit()
