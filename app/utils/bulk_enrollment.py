"""
Bulk Enrollment Utility
Upload CSV files to enroll multiple students at once
"""
import csv
import io
from werkzeug.security import generate_password_hash
from app.models import User, Student, Enrollment, ClassInstance
from app import db
import uuid


def parse_enrollment_csv(file_content):
    """
    Parse CSV file for student enrollment
    Expected columns: student_id, first_name, last_name, email, major (optional)
    """
    try:
        # Decode file content
        if isinstance(file_content, bytes):
            file_content = file_content.decode('utf-8')
        
        csv_file = io.StringIO(file_content)
        reader = csv.DictReader(csv_file)
        
        students_data = []
        errors = []
        
        required_fields = ['student_id', 'first_name', 'last_name', 'email']
        
        for row_num, row in enumerate(reader, start=2):  # Start at 2 (1 is header)
            # Check required fields
            missing_fields = [field for field in required_fields if not row.get(field)]
            if missing_fields:
                errors.append(f"Row {row_num}: Missing required fields: {', '.join(missing_fields)}")
                continue
            
            # Validate email domain
            email = row['email'].strip().lower()
            if not email.endswith('@acem.ac.in'):
                errors.append(f"Row {row_num}: Invalid email domain. Must end with @acem.ac.in")
                continue
            
            try:
                enrollment_year = int(row.get('enrollment_year', 2024))
            except (TypeError, ValueError):
                errors.append(f"Row {row_num}: Enrollment year must be a number")
                continue

            students_data.append({
                'student_id': row['student_id'].strip(),
                'first_name': row['first_name'].strip(),
                'last_name': row['last_name'].strip(),
                'email': email,
                'major': (row.get('major') or 'Undeclared').strip(),
                'enrollment_year': enrollment_year
            })
        
        return students_data, errors
    
    except Exception as e:
        return [], [f"Error parsing CSV: {str(e)}"]


def bulk_enroll_students(class_id, students_data, enrolled_by):
    """
    Enroll multiple students in a class
    Creates user accounts if they don't exist
    """
    results = {
        'success': [],
        'errors': [],
        'created_accounts': [],
        'existing_accounts': [],
        'already_enrolled': []
    }
    
    class_instance = ClassInstance.query.get(class_id)
    if not class_instance:
        results['errors'].append("Class not found")
        return results
    
    active_count = Enrollment.query.filter_by(
        class_instance_id=class_id,
        status='active'
    ).count()

    for student_data in students_data:
        try:
            # A savepoint isolates one invalid row instead of rolling back previously
            # processed rows and reporting them as successful.
            with db.session.begin_nested():
                user = User.query.filter_by(email=student_data['email']).first()
                created_account = False

                if not user:
                    if class_instance.max_students and active_count >= class_instance.max_students:
                        raise ValueError('Class is full')
                    if Student.query.filter_by(student_id=student_data['student_id']).first():
                        raise ValueError('Student ID is already assigned to another account')

                    user = User(
                        id=str(uuid.uuid4()),
                        email=student_data['email'],
                        password_hash=generate_password_hash('student123'),
                        first_name=student_data['first_name'],
                        last_name=student_data['last_name'],
                        role='student',
                        is_active=True
                    )
                    db.session.add(user)
                    db.session.flush()
                    db.session.add(Student(
                        id=str(uuid.uuid4()),
                        user_id=user.id,
                        student_id=student_data['student_id'],
                        major=student_data['major'],
                        enrollment_year=student_data['enrollment_year']
                    ))
                    db.session.flush()
                    created_account = True
                else:
                    if user.role != 'student' or not user.is_active:
                        raise ValueError('Account exists but is not an active student account')
                    if not Student.query.filter_by(user_id=user.id).first():
                        raise ValueError('Student account is missing its student profile')

                existing_enrollment = Enrollment.query.filter_by(
                    student_id=user.id,
                    class_instance_id=class_id
                ).first()
                if existing_enrollment and existing_enrollment.status == 'active':
                    results['already_enrolled'].append(student_data['email'])
                    continue

                if class_instance.max_students and active_count >= class_instance.max_students:
                    raise ValueError('Class is full')

                if existing_enrollment:
                    existing_enrollment.status = 'active'
                else:
                    db.session.add(Enrollment(
                        id=str(uuid.uuid4()),
                        student_id=user.id,
                        class_instance_id=class_id,
                        enrolled_by=enrolled_by,
                        enrollment_method='bulk_upload',
                        status='active'
                    ))
                db.session.flush()

            active_count += 1
            class_instance.current_enrollment = active_count
            results['success'].append(student_data['email'])
            if created_account:
                results['created_accounts'].append(student_data['email'])
            else:
                results['existing_accounts'].append(student_data['email'])
        except Exception as e:
            results['errors'].append(f"{student_data['email']}: {str(e)}")
            continue
    
    try:
        class_instance.current_enrollment = Enrollment.query.filter_by(
            class_instance_id=class_id,
            status='active'
        ).count()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        results['errors'].append(f"Database error: {str(e)}")
    
    return results


def generate_enrollment_template():
    """
    Generate a CSV template for bulk enrollment
    """
    template_data = [
        ['student_id', 'first_name', 'last_name', 'email', 'major', 'enrollment_year'],
        ['STU001', 'John', 'Doe', 'john.doe@acem.ac.in', 'Computer Science', '2024'],
        ['STU002', 'Jane', 'Smith', 'jane.smith@acem.ac.in', 'Information Technology', '2024'],
        ['STU003', 'Bob', 'Johnson', 'bob.johnson@acem.ac.in', 'Electronics', '2024']
    ]
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(template_data)
    
    return output.getvalue()


def validate_class_enrollment(class_id):
    """
    Validate and get statistics for class enrollment
    """
    class_instance = ClassInstance.query.get(class_id)
    if not class_instance:
        return None
    
    enrollments = Enrollment.query.filter_by(
        class_instance_id=class_id,
        status='active'
    ).all()
    
    return {
        'class_code': class_instance.class_code,
        'course_name': class_instance.course.name,
        'max_students': class_instance.max_students,
        'current_enrollment': len(enrollments),
        'available_seats': class_instance.max_students - len(enrollments) if class_instance.max_students else None,
        'is_full': class_instance.max_students and len(enrollments) >= class_instance.max_students
    }
