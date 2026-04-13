"""API module."""

from __future__ import annotations

from .routes import create_app, health_check, get_user

__all__ = ["create_app", "health_check", "get_user"]
