"""Tests for auth service."""

from __future__ import annotations

import pytest
from src.auth import AuthService, hash_password, verify_password, generate_token


def test_hash_password_returns_tuple() -> None:
    """Test that hash_password returns (digest, salt)."""
    digest, salt = hash_password("secret123")
    assert isinstance(digest, str)
    assert isinstance(salt, str)
    assert len(digest) == 64


def test_verify_password_correct() -> None:
    """Test verify_password with correct credentials."""
    digest, salt = hash_password("secret123")
    result = verify_password("secret123", digest, salt)
    assert result is True


def test_verify_password_incorrect() -> None:
    """Test verify_password with wrong password."""
    digest, salt = hash_password("secret123")
    result = verify_password("wrongpassword", digest, salt)
    assert result is False


def test_generate_token_returns_hex() -> None:
    """Test that generate_token returns a hex string."""
    token = generate_token("user_123")
    assert isinstance(token, str)
    assert len(token) == 64


def test_auth_service_login_success() -> None:
    """Test AuthService.login with valid credentials."""
    service = AuthService()
    result = service.login("alice", "password123")
    assert "token" in result
    assert result["user"] == "alice"


def test_auth_service_login_missing_username() -> None:
    """Test AuthService.login with missing username."""
    service = AuthService()
    result = service.login("", "password")
    assert "error" in result


def test_auth_service_logout() -> None:
    """Test AuthService.logout."""
    service = AuthService()
    login_result = service.login("alice", "password123")
    token = login_result["token"]
    assert service.logout(token) is True


def test_auth_service_verify_token() -> None:
    """Test AuthService.verify_token."""
    service = AuthService()
    login_result = service.login("alice", "password123")
    token = login_result["token"]
    assert service.verify_token(token) == "alice"
    assert service.verify_token("invalid_token") is None
