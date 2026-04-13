"""User model for database operations."""

from __future__ import annotations

from typing import Any


class UserModel:
    """User data access object."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def find_by_username(self, username: str) -> dict[str, Any] | None:
        """Find a user by username."""
        result = self._db.execute(
            "SELECT * FROM users WHERE username = $1",
            {"username": username},
        )
        return result[0] if result else None

    def create(self, username: str, email: str) -> dict[str, Any]:
        """Create a new user."""
        id = self._db.execute(
            "INSERT INTO users (username, email) VALUES ($1, $2) RETURNING id",
            {"username": username, "email": email},
        )
        return {"id": id, "username": username, "email": email}
