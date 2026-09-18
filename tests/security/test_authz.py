from __future__ import annotations

from smp.protocol.auth import Principal, Scope, required_scope


def test_scope_enforcement():
    """S-007: Test that methods map to correct scopes and are enforced."""
    # Map a few methods to their required scopes
    test_cases = [
        ("smp/navigate", Scope.READ),
        ("smp/update", Scope.WRITE),
        ("smp/sandbox/execute", Scope.ADMIN),
        ("smp/unknown_method", Scope.ADMIN),  # Default
    ]

    for method, expected_scope in test_cases:
        assert required_scope(method) == expected_scope


def test_authorization_access():
    """S-007: Test that principal scope is checked against required scope."""
    # User with only READ scope
    read_principal = Principal(key_id="read_id", name="reader", scopes=frozenset({Scope.READ}))

    # User with WRITE scope
    write_principal = Principal(key_id="write_id", name="writer", scopes=frozenset({Scope.WRITE}))

    # Admin user
    admin_principal = Principal(key_id="admin_id", name="admin", scopes=frozenset({Scope.ADMIN}))

    # Test READ method
    method_read = "smp/navigate"
    assert read_principal.has(required_scope(method_read))
    assert write_principal.has(required_scope(method_read)) is False  # WRONG! Wait.
    # Actually, does WRITE imply READ?
    # In Principal.has: return Scope.ADMIN in self.scopes or scope in self.scopes
    # It DOES NOT imply. Only ADMIN implies others.

    # Let's verify based on the code in smp/protocol/auth.py:
    # def has(self, scope: Scope) -> bool:
    #     return Scope.ADMIN in self.scopes or scope in self.scopes

    # So WRITE does NOT have READ.
    assert write_principal.has(required_scope(method_read)) is False
    assert admin_principal.has(required_scope(method_read))

    # Test WRITE method
    method_write = "smp/update"
    assert read_principal.has(required_scope(method_write)) is False
    assert write_principal.has(required_scope(method_write))
    assert admin_principal.has(required_scope(method_write))

    # Test ADMIN method
    method_admin = "smp/sandbox/execute"
    assert read_principal.has(required_scope(method_admin)) is False
    assert write_principal.has(required_scope(method_admin)) is False
    assert admin_principal.has(required_scope(method_admin))


def test_admin_scope_override():
    """C-005: Test that ADMIN scope overrides all other scope checks."""
    admin_principal = Principal(
        key_id="admin_id",
        name="admin",
        scopes=frozenset({Scope.ADMIN}),
    )

    assert admin_principal.has(Scope.READ)
    assert admin_principal.has(Scope.WRITE)
    assert admin_principal.has(Scope.ADMIN)
