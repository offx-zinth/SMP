from __future__ import annotations

import time

from smp.protocol.auth import AuthPolicy, Principal, Scope


def test_key_rotation_token_update():
    """C-004: Verify that an API key's token can be rotated."""
    policy = AuthPolicy()
    old_token = "old_secret_token"
    new_token = "new_secret_token"

    principal = Principal(key_id="old_id", name="test_user", scopes=frozenset({Scope.READ}))
    policy.keys[old_token] = principal

    rotated = policy.rotate_key(old_token, new_token=new_token)

    assert rotated is not None
    assert rotated.key_id == new_token[:8]
    assert old_token not in policy.keys
    assert new_token in policy.keys
    assert policy.keys[new_token].name == "test_user"


def test_key_rotation_expiration_update():
    """C-004: Verify that an API key's expiration can be updated."""
    policy = AuthPolicy()
    token = "secret_token"

    principal = Principal(
        key_id="token_id", name="test_user", scopes=frozenset({Scope.READ}), expires_at=time.time() + 100
    )
    policy.keys[token] = principal

    # Rotate expiration to 200 seconds from now
    rotated = policy.rotate_key(token, expires_in_seconds=200)

    assert rotated is not None
    assert rotated.expires_at > principal.expires_at
    assert token in policy.keys
    assert policy.keys[token].expires_at == rotated.expires_at


def test_key_rotation_not_found():
    """Verify rotation fails for non-existent keys."""
    policy = AuthPolicy()
    result = policy.rotate_key("nonexistent", new_token="new")
    assert result is None
