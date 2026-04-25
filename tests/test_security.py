"""Phase 4 tests: authentication, authorization, request hardening.

These tests bypass the global env loader by passing a hand-crafted
:class:`AuthPolicy` straight into :func:`create_app`.  This keeps the
test deterministic regardless of operator-set environment variables.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from smp.protocol.auth import AuthPolicy, Principal, Scope
from smp.protocol.server import create_app


def _policy(**overrides: Any) -> AuthPolicy:
    """Build a strict (non-open-mode) policy with named principals."""
    keys = {
        "key-admin": Principal(
            key_id="admin", name="admin", scopes=frozenset({Scope.READ, Scope.WRITE, Scope.ADMIN})
        ),
        "key-writer": Principal(
            key_id="writer", name="writer", scopes=frozenset({Scope.READ, Scope.WRITE})
        ),
        "key-reader": Principal(
            key_id="reader", name="reader", scopes=frozenset({Scope.READ})
        ),
    }
    policy = AuthPolicy(keys=keys, open_mode=False)
    for k, v in overrides.items():
        setattr(policy, k, v)
    return policy


def _client(tmp_path: Path, policy: AuthPolicy) -> TestClient:
    graph_path = tmp_path / "graph.smpg"
    app = create_app(graph_path=str(graph_path), auth_policy=policy)
    return TestClient(app)


@pytest.fixture()
def secure_client(tmp_path: Path) -> Iterator[TestClient]:
    with _client(tmp_path, _policy()) as client:
        yield client


@pytest.fixture()
def open_client(tmp_path: Path) -> Iterator[TestClient]:
    with _client(tmp_path, AuthPolicy(open_mode=True)) as client:
        yield client


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class TestAuthentication:
    def test_missing_token_is_rejected(self, secure_client: TestClient) -> None:
        response = secure_client.post("/rpc", json={"jsonrpc": "2.0", "method": "smp/search", "id": 1})
        assert response.status_code == 401
        body = response.json()
        assert body["error"]["code"] == -32001

    def test_unknown_token_is_rejected(self, secure_client: TestClient) -> None:
        response = secure_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "id": 1},
            headers={"Authorization": "Bearer not-a-real-key"},
        )
        assert response.status_code == 401

    def test_bearer_token_accepted(self, secure_client: TestClient) -> None:
        response = secure_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "anything"}, "id": 1},
            headers={"Authorization": "Bearer key-reader"},
        )
        assert response.status_code == 200

    def test_x_api_key_header_accepted(self, secure_client: TestClient) -> None:
        response = secure_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"X-SMP-Api-Key": "key-reader"},
        )
        assert response.status_code == 200

    def test_health_is_public(self, secure_client: TestClient) -> None:
        assert secure_client.get("/health").status_code == 200

    def test_stats_requires_auth(self, secure_client: TestClient) -> None:
        assert secure_client.get("/stats").status_code == 401

    def test_methods_requires_auth(self, secure_client: TestClient) -> None:
        assert secure_client.get("/methods").status_code == 401


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


class TestAuthorization:
    def test_reader_cannot_write(self, secure_client: TestClient) -> None:
        response = secure_client.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "method": "smp/update",
                "params": {"node_id": "x", "patch": {}},
                "id": 1,
            },
            headers={"Authorization": "Bearer key-reader"},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == -32002

    def test_writer_cannot_admin(self, secure_client: TestClient) -> None:
        response = secure_client.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "method": "smp/sandbox/spawn",
                "params": {},
                "id": 1,
            },
            headers={"Authorization": "Bearer key-writer"},
        )
        assert response.status_code == 403

    def test_admin_can_invoke_admin_methods(self, secure_client: TestClient) -> None:
        response = secure_client.post(
            "/rpc",
            json={
                "jsonrpc": "2.0",
                "method": "smp/sandbox/spawn",
                "params": {"session_id": "s1"},
                "id": 1,
            },
            headers={"Authorization": "Bearer key-admin"},
        )
        # The handler may decline, but the auth layer must let the request through.
        assert response.status_code == 200

    def test_unknown_method_returns_jsonrpc_error_not_500(self, secure_client: TestClient) -> None:
        response = secure_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/does/not/exist", "id": 9},
            headers={"Authorization": "Bearer key-admin"},
        )
        assert response.status_code == 200
        assert response.json()["error"]["code"] == -32601

    def test_invalidate_requires_write(self, secure_client: TestClient) -> None:
        no_auth = secure_client.post("/smp/invalidate", json={"file_path": "x.py"})
        assert no_auth.status_code == 401

        reader = secure_client.post(
            "/smp/invalidate",
            json={"file_path": "x.py"},
            headers={"Authorization": "Bearer key-reader"},
        )
        assert reader.status_code == 403


# ---------------------------------------------------------------------------
# Request hardening
# ---------------------------------------------------------------------------


class TestRequestHardening:
    def test_request_size_cap_rejects_oversized_body(self, tmp_path: Path) -> None:
        policy = _policy()
        policy.max_request_bytes = 256
        with _client(tmp_path, policy) as client:
            big = "x" * 1024
            response = client.post(
                "/rpc",
                json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": big}, "id": 1},
                headers={"Authorization": "Bearer key-reader"},
            )
            assert response.status_code == 413

    def test_invalid_json_yields_parse_error(self, secure_client: TestClient) -> None:
        response = secure_client.post(
            "/rpc",
            content=b"not really json",
            headers={
                "Authorization": "Bearer key-reader",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 200
        assert response.json()["error"]["code"] == -32700

    def test_invalid_request_shape_returns_invalid_request(self, secure_client: TestClient) -> None:
        response = secure_client.post(
            "/rpc",
            json=["not", "an", "object"],
            headers={"Authorization": "Bearer key-reader"},
        )
        assert response.status_code == 200
        assert response.json()["error"]["code"] == -32600

    def test_internal_error_is_redacted(
        self, secure_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from smp.protocol import server as server_module

        async def bomb(*_: Any, **__: Any) -> None:
            raise RuntimeError("DB password 's3cret123' got corrupted")

        monkeypatch.setitem(server_module._HANDLERS, "smp/search", bomb)

        response = secure_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"Authorization": "Bearer key-reader"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["error"]["code"] == -32603
        # The raw exception text must NOT leak through the wire.
        assert "DB password" not in json.dumps(body)
        assert "s3cret123" not in json.dumps(body)


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimit:
    def test_rate_limit_returns_429(self, tmp_path: Path) -> None:
        policy = _policy()
        policy.rate_limit_per_minute = 3
        with _client(tmp_path, policy) as client:
            payload = {"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1}
            headers = {"Authorization": "Bearer key-reader"}
            for _ in range(3):
                ok = client.post("/rpc", json=payload, headers=headers)
                assert ok.status_code == 200
            blocked = client.post("/rpc", json=payload, headers=headers)
            assert blocked.status_code == 429
            assert blocked.json()["error"]["code"] == -32003


# ---------------------------------------------------------------------------
# Open mode (developer convenience)
# ---------------------------------------------------------------------------


class TestOpenMode:
    def test_no_token_required_in_open_mode(self, open_client: TestClient) -> None:
        response = open_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
        )
        assert response.status_code == 200
        # Even admin methods are allowed in open mode.
        admin = open_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/sandbox/spawn", "params": {"session_id": "s1"}, "id": 2},
        )
        assert admin.status_code == 200


# ---------------------------------------------------------------------------
# Scope policy table
# ---------------------------------------------------------------------------


class TestScopePolicy:
    def test_every_handler_has_a_scope(self) -> None:
        from smp.protocol.auth import required_scope
        from smp.protocol.server import _HANDLERS

        for method in _HANDLERS:
            scope = required_scope(method)
            assert scope in (Scope.READ, Scope.WRITE, Scope.ADMIN)

    def test_methods_endpoint_advertises_scopes(self, secure_client: TestClient) -> None:
        response = secure_client.get("/methods", headers={"Authorization": "Bearer key-admin"})
        assert response.status_code == 200
        for entry in response.json()["methods"]:
            assert entry["scope"] in {"read", "write", "admin"}


# ---------------------------------------------------------------------------
# Auth policy from disk
# ---------------------------------------------------------------------------


class TestAuthPolicyFromEnv:
    def test_missing_keys_file_falls_back_to_open_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SMP_API_KEYS_FILE", str(tmp_path / "missing.json"))
        policy = AuthPolicy.from_env()
        assert policy.open_mode is True

    def test_well_formed_keys_file_loads(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        keys_file = tmp_path / "keys.json"
        keys_file.write_text(
            json.dumps(
                {
                    "keys": {
                        "abc123": {"name": "team-a", "scopes": ["read", "write"]},
                        "def456": {"name": "team-b", "scopes": ["read"]},
                    }
                }
            )
        )
        monkeypatch.setenv("SMP_API_KEYS_FILE", str(keys_file))
        policy = AuthPolicy.from_env()
        assert policy.open_mode is False
        assert len(policy.keys) == 2
        assert "abc123" in policy.keys
        assert Scope.WRITE in policy.keys["abc123"].scopes
        assert Scope.WRITE not in policy.keys["def456"].scopes
