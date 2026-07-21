"""
Configuration file for the QRotation with real-time sync and QR rotation
"""
import os
from datetime import timedelta
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Base configuration class"""
    # Flask settings
    SECRET_KEY = os.environ.get('SECRET_KEY', 'vibetrack_super_secret_key_2024_secure_flask_app')
    
    # Session settings for Flask-Login
    SESSION_TYPE = 'filesystem'
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_COOKIE_SECURE = False  # Set True in production with HTTPS
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_DURATION = timedelta(days=7)
    REMEMBER_COOKIE_SECURE = False  # Set True in production
    REMEMBER_COOKIE_HTTPONLY = True
    
    # Database settings
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # JWT settings
    JWT_SECRET = os.environ.get('JWT_SECRET', 'your_jwt_secret_key_here')
    JWT_EXPIRY_HOURS = 168  # 7 days
    
    # QR Code settings
    QR_SECRET = os.environ.get('QR_SECRET', 'vibetrack_qr_secret_key_2024_secure')
    QR_EXPIRY_SECONDS = int(os.environ.get('QR_EXPIRY_SECONDS', 90))  # QR codes expire in 90 seconds
    QR_ROTATION_INTERVAL = int(os.environ.get('QR_ROTATION_INTERVAL', 30))  # Rotate QR every 30 seconds
    QR_GRACE_PERIOD_SECONDS = int(os.environ.get('QR_GRACE_PERIOD_SECONDS', 30))  # Grace period for network delays
    
    # Server settings
    HOST = os.environ.get('HOST', '0.0.0.0')
    PORT = int(os.environ.get('PORT', 5000))
    DEBUG = os.environ.get('DEBUG', 'True').lower() == 'true'
    SEED_INITIAL_DATA = os.environ.get('SEED_INITIAL_DATA', 'True').lower() == 'true'
    
    # Email domain restriction
    ALLOWED_EMAIL_DOMAIN = '@acem.ac.in'
    
    # Attendance settings
    LATE_THRESHOLD_MINUTES = 5  # Students marked late after 5 minutes
    GRACE_PERIOD_MINUTES = 3  # Grace period for attendance
    CAMPUS_TIMEZONE = os.environ.get('CAMPUS_TIMEZONE', 'Asia/Kolkata')
    
    # Session settings
    SESSION_DURATION_HOURS = 1  # Default session duration
    
    # Email settings (Flask-Mail)
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'False').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@attendance.com')
    MAIL_MAX_EMAILS = None
    MAIL_ASCII_ATTACHMENTS = False
    
    # Email notification settings
    ENABLE_EMAIL_NOTIFICATIONS = os.environ.get('ENABLE_EMAIL_NOTIFICATIONS', 'False').lower() == 'true'
    LOW_ATTENDANCE_THRESHOLD = int(os.environ.get('LOW_ATTENDANCE_THRESHOLD', 75))  # Percentage
    SEND_DAILY_REMINDERS = os.environ.get('SEND_DAILY_REMINDERS', 'False').lower() == 'true'
    
    # Geolocation settings (configurable via .env)
    ENABLE_GEOLOCATION = os.environ.get('ENABLE_GEOLOCATION', 'True').lower() == 'true'
    # Keep this opt-in so deployments that do not have reliable location data do not
    # block attendance unexpectedly. When enabled, a scan without a verified location
    # is rejected by the shared attendance service.
    REQUIRE_GEOLOCATION = os.environ.get('REQUIRE_GEOLOCATION', 'False').lower() == 'true'
    LOCATION_VERIFICATION_RADIUS = int(os.environ.get('LOCATION_VERIFICATION_RADIUS', 100))  # Radius in meters
    MAX_REGISTERED_DEVICES = int(os.environ.get('MAX_REGISTERED_DEVICES', 2))
    FRAUD_SCAN_WINDOW_SECONDS = int(os.environ.get('FRAUD_SCAN_WINDOW_SECONDS', 8))
    FRAUD_SHARED_QR_MIN_SCANS = int(os.environ.get('FRAUD_SHARED_QR_MIN_SCANS', 8))
    # Optional mapping of room names to Bluetooth beacon names, stored as JSON.
    # Example: {"Room 101": ["ACEM-101-BEACON"]}
    CLASSROOM_BEACONS = os.environ.get('CLASSROOM_BEACONS', '{}')
    
    # Classroom locations (latitude, longitude, radius in meters)
    # Read from environment variables for easy configuration
    CLASSROOM_LAT = float(os.environ.get('CLASSROOM_LAT', 19.0760))
    CLASSROOM_LNG = float(os.environ.get('CLASSROOM_LNG', 72.8777))
    CLASSROOM_RADIUS = int(os.environ.get('CLASSROOM_RADIUS', 100))
    
    # Classroom locations dictionary (for backward compatibility)
    CLASSROOM_LOCATIONS = {
        'Room 101': {'lat': CLASSROOM_LAT, 'lng': CLASSROOM_LNG, 'radius': CLASSROOM_RADIUS},
        'Room 102': {'lat': CLASSROOM_LAT, 'lng': CLASSROOM_LNG, 'radius': CLASSROOM_RADIUS},
        'Room 103': {'lat': CLASSROOM_LAT, 'lng': CLASSROOM_LNG, 'radius': CLASSROOM_RADIUS},
        'Lab 1': {'lat': CLASSROOM_LAT, 'lng': CLASSROOM_LNG, 'radius': CLASSROOM_RADIUS},
        'Lab 2': {'lat': CLASSROOM_LAT, 'lng': CLASSROOM_LNG, 'radius': CLASSROOM_RADIUS},
        # All rooms use the same coordinates from .env
    }


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    

class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False


# Config dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
