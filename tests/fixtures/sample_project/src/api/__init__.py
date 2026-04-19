"""API module."""

from __future__ import annotations

from .routes import create_app, get_user, health_check

__all__ = ["create_app", "health_check", "get_user"]
