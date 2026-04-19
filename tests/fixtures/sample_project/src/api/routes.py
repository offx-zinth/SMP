"""API routes for the sample project."""

from __future__ import annotations

from typing import Any

from src.auth import AuthService
from src.db import DatabaseConnection, UserModel


def create_app() -> dict[str, Any]:
    """Create and return the API app configuration."""
    return {
        "name": "sample_api",
        "version": "1.0.0",
        "endpoints": ["/health", "/users/{id}", "/login"],
    }


def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "service": "sample_api"}


def get_user(user_id: str) -> dict[str, Any] | None:
    """Get a user by ID."""
    db = DatabaseConnection()
    db.connect()
    model = UserModel(db)
    result = model.find_by_username(user_id)
    return result


def login_user(username: str, password: str) -> dict[str, Any]:
    """Login a user."""
    auth = AuthService()
    return auth.login(username, password)
