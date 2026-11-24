"""Password hashing and opaque server-side owner sessions."""

import secrets

from pwdlib import PasswordHash

from backend.app.persistence.auth_repository import AuthRepository, utc_now

PASSWORD_HASHER = PasswordHash.recommended()
SESSION_COOKIE = "atlas_session"
DEVICE_COOKIE = "atlas_device"
CSRF_COOKIE = "atlas_csrf"
CSRF_HEADER = "x-csrf-token"


def validate_master_password(password: str) -> None:
    if len(password) < 14 or len(password) > 1024:
        raise ValueError("A senha mestra deve ter entre 14 e 1024 caracteres.")


class AuthService:
    def __init__(self, repository: AuthRepository) -> None:
        self.repository = repository

    @staticmethod
    def hash_password(password: str) -> str:
        validate_master_password(password)
        return PASSWORD_HASHER.hash(password)

    def authenticate(self, password: str) -> bool:
        now = utc_now()
        if self.repository.is_locked(now):
            return False
        if not password or len(password) > 1024:
            self.repository.record_login_failure(now)
            return False
        password_hash = self.repository.password_hash()
        valid = bool(password_hash and PASSWORD_HASHER.verify(password, password_hash))
        if valid:
            self.repository.record_login_success()
        else:
            self.repository.record_login_failure(now)
        return valid

    def issue_session(self, device_id: str | None, label: str, user_agent: str) -> tuple[str, dict]:
        token = secrets.token_urlsafe(32)
        device_id = device_id if device_id and len(device_id) <= 64 else secrets.token_urlsafe(24)
        session = self.repository.create_session(device_id, label, user_agent, token)
        return token, session
