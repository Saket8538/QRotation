"""Durable, rotating QR code generation and validation for attendance."""
import base64
import hashlib
import hmac
import io
import json
import secrets
from datetime import timedelta
from urllib.parse import quote

import qrcode
from flask import current_app, has_app_context

from app import db
from app.models import QRToken
from app.utils.time_utils import utc_now_naive
from config import Config


class QRCodeGenerator:
    """Issue opaque, database-backed QR tokens for active class sessions."""

    @staticmethod
    def _setting(name, default):
        return current_app.config.get(name, default) if has_app_context() else default

    @classmethod
    def generate_secure_qr(cls, session_id, base_url='http://localhost:5000'):
        """Create a QR image and persist the opaque token before returning it."""
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
        expiry_seconds = int(cls._setting('QR_EXPIRY_SECONDS', Config.QR_EXPIRY_SECONDS))
        expires_at = utc_now_naive() + timedelta(seconds=expiry_seconds)

        db.session.add(QRToken(
            session_id=session_id,
            token_hash=token_hash,
            expires_at=expires_at
        ))
        cls._cleanup_expired_tokens(commit=False)
        # The QR can be scanned immediately. Persist it before returning so it also
        # works across worker processes and after an application restart.
        db.session.commit()

        qr_data = {'token': token, 'version': 2}
        encoded_data = quote(json.dumps(qr_data, separators=(',', ':')), safe='')
        # A fragment is never sent to the web server, preventing a short-lived token
        # from appearing in access logs or a Referer header.
        qr_url = f"{base_url}/student/scan#data={encoded_data}"

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2
        )
        qr.add_data(qr_url)
        qr.make(fit=True)
        image = qr.make_image(fill_color='black', back_color='white')
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')

        return {
            'qr_code': f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}",
            'qr_data': qr_data,
            'expires_at': expires_at.isoformat(),
            'session_id': session_id,
            # Kept for the existing route contract. This is a hash, never the secret.
            'secret': token_hash,
            'token_hash': token_hash
        }

    @classmethod
    def _cleanup_expired_tokens(cls, commit=True):
        grace = int(cls._setting('QR_GRACE_PERIOD_SECONDS', Config.QR_GRACE_PERIOD_SECONDS))
        cutoff = utc_now_naive() - timedelta(seconds=grace)
        QRToken.query.filter(QRToken.expires_at < cutoff).delete(synchronize_session=False)
        if commit:
            db.session.commit()

    @classmethod
    def validate_qr(cls, qr_data):
        """Validate a server-issued opaque token or a legacy signed QR payload."""
        try:
            if isinstance(qr_data, str):
                qr_data = json.loads(qr_data)
            if not isinstance(qr_data, dict):
                return {'isValid': False, 'error': 'Invalid QR code format'}

            if 'token' in qr_data:
                return cls._validate_token_qr(qr_data)
            if 'signature' in qr_data:
                return cls._validate_legacy_qr(qr_data)
            return {'isValid': False, 'error': 'Invalid QR code format'}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {'isValid': False, 'error': 'Invalid QR code format'}

    @classmethod
    def _validate_token_qr(cls, qr_data):
        token = qr_data.get('token')
        if not isinstance(token, str) or not 20 <= len(token) <= 255:
            return {'isValid': False, 'error': 'Invalid QR code'}

        token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
        record = QRToken.query.filter_by(token_hash=token_hash).first()
        if not record or record.revoked_at:
            return {'isValid': False, 'error': 'Invalid or expired QR code. Please scan the latest QR code.'}

        grace = int(cls._setting('QR_GRACE_PERIOD_SECONDS', Config.QR_GRACE_PERIOD_SECONDS))
        if utc_now_naive() > record.expires_at + timedelta(seconds=grace):
            return {'isValid': False, 'error': 'QR code has expired. Please scan the latest QR code.'}

        return {'isValid': True, 'sessionId': record.session_id, 'tokenId': record.id}

    @classmethod
    def _validate_legacy_qr(cls, qr_data):
        """Validate signed codes issued by older application versions."""
        required_fields = ['sessionId', 'timestamp', 'nonce', 'signature', 'expiresAt']
        if any(field not in qr_data for field in required_fields):
            return {'isValid': False, 'error': 'Invalid QR code format'}

        try:
            from datetime import datetime
            expires_at = datetime.fromisoformat(str(qr_data['expiresAt']).replace('Z', '+00:00'))
            now_ms = int(utc_now_naive().timestamp() * 1000)
            expires_at_ms = int(expires_at.timestamp() * 1000)
            timestamp = int(qr_data['timestamp'])
        except (TypeError, ValueError):
            return {'isValid': False, 'error': 'Invalid QR code format'}

        expiry = int(cls._setting('QR_EXPIRY_SECONDS', Config.QR_EXPIRY_SECONDS)) * 1000
        if now_ms > expires_at_ms or now_ms - timestamp > expiry:
            return {'isValid': False, 'error': 'QR code has expired. Please scan the latest QR code.'}

        payload = f"{qr_data['sessionId']}-{timestamp}-{qr_data['nonce']}"
        expected = hmac.new(
            cls._setting('QR_SECRET', Config.QR_SECRET).encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, str(qr_data['signature'])):
            return {'isValid': False, 'error': 'Invalid QR code signature'}
        return {'isValid': True, 'sessionId': qr_data['sessionId']}

    @classmethod
    def invalidate_session_tokens(cls, session_id):
        """Revoke all outstanding tokens for a completed or cancelled session."""
        QRToken.query.filter_by(session_id=session_id, revoked_at=None).update(
            {'revoked_at': utc_now_naive()}, synchronize_session=False
        )

    @classmethod
    def get_active_token_count(cls):
        cls._cleanup_expired_tokens()
        return QRToken.query.filter_by(revoked_at=None).count()
