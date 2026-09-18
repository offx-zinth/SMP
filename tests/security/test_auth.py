from __future__ import annotations

import time

from smp.protocol.auth import AuthPolicy, Principal, Scope, extract_token


def test_auth_open_mode():
    """S-001: Test that open mode grants all scopes to dev principal."""
    policy = AuthPolicy(open_mode=True)
    principal = policy.authenticate(None)
    assert principal is not None
    assert principal.name == "dev"
    assert Scope.ADMIN in principal.scopes
    assert Scope.WRITE in principal.scopes
    assert Scope.READ in principal.scopes


def test_auth_valid_api_key():
    """S-002: Test that a valid API key authenticates correctly."""
    token = "valid_token_123"
    policy = AuthPolicy(
        keys={
            token: Principal(
                key_id=token[:8],
                name="test_user",
                scopes=frozenset({Scope.READ}),
            )
        }
    )
    principal = policy.authenticate(token)
    assert principal is not None
    assert principal.name == "test_user"
    assert Scope.READ in principal.scopes


def test_auth_invalid_api_key():
    """S-003: Test that an unknown API key returns None."""
    policy = AuthPolicy(keys={"valid_token": Principal("val", "user", frozenset({Scope.READ}))})
    assert policy.authenticate("invalid_token") is None


def test_auth_expired_api_key():
    """S-004: Test that an expired API key returns None."""
    token = "expired_token"
    policy = AuthPolicy(
        keys={
            token: Principal(
                key_id=token[:8],
                name="expired_user",
                scopes=frozenset({Scope.READ}),
                expires_at=time.time() - 3600,
            )
        }
    )
    assert policy.authenticate(token) is None


def test_token_extraction():
    """S-005: Test token extraction from different headers."""
    token = "my_secret_token"

    # Bearer token
    headers_bearer = {"authorization": f"Bearer {token}"}
    assert extract_token(headers_bearer) == token

    # X-SMP-Api-Key
    headers_x_smp = {"x-smp-api-key": token}
    assert extract_token(headers_x_smp) == token

    # Case insensitive bearer
    headers_bearer_low = {"authorization": f"bearer {token}"}
    assert extract_token(headers_bearer_low) == token

    # Invalid/Missing
    assert extract_token({}) is None
    assert extract_token({"authorization": "Basic 123"}) is None
    assert extract_token({"authorization": "Bearer "}) is None


def test_auth_missing_token_closed_mode():
    """S-006: Test that missing token returns None when not in open mode."""
    policy = AuthPolicy(open_mode=False)
    assert policy.authenticate(None) is None
