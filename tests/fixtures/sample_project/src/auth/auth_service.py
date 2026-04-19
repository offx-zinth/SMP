"""Authentication service for the sample project."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Hash a password with a salt using SHA-256."""
    if salt is None:
        salt = uuid.uuid4().hex[:16]
    combined = f"{password}{salt}".encode()
    digest = hashlib.sha256(combined).hexdigest()
    return digest, salt


def verify_password(password: str, hashed: str, salt: str) -> bool:
    """Verify a password against a hash."""
    computed, _ = hash_password(password, salt)
    return computed == hashed


def generate_token(user_id: str, secret: str = "default_secret") -> str:
    """Generate a simple auth token."""
    payload = f"{user_id}:{datetime.now(UTC).isoformat()}"
    combined = f"{payload}{secret}".encode()
    return hashlib.sha256(combined).hexdigest()


class AuthService:
    """Main authentication service."""

    def __init__(self) -> None:
        self._sessions: dict[str, str] = {}
        self._secret = "default_secret"

    def login(self, username: str, password: str) -> dict[str, str]:
        """Authenticate a user and return a session token."""
        if not username or not password:
            return {"error": "missing credentials"}

        token = generate_token(username, self._secret)
        self._sessions[token] = username
        return {"token": token, "user": username}

    def logout(self, token: str) -> bool:
        """End a user session."""
        if token in self._sessions:
            del self._sessions[token]
            return True
        return False

    def verify_token(self, token: str) -> str | None:
        """Check if a token is valid and return the username."""
        return self._sessions.get(token)


def get_current_user(token: str | None) -> str | None:
    """Helper to get current user from token."""
    if not token:
        return None
    service = AuthService()
    return service.verify_token(token)
