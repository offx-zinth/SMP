from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from smp.protocol.auth import Principal, Scope
from smp.protocol.server import (
    _HANDLERS,
    _dispatch,
    _MethodNotFoundError,
    create_app,
)


class MockPrincipal(Principal):
    def __init__(
        self,
        name: str = "test-user",
        scopes: set[Scope] | None = None,
    ) -> None:
        if scopes is None:
            scopes = {Scope.READ, Scope.WRITE, Scope.ADMIN}
        # Use object.__setattr__ because Principal is frozen
        object.__setattr__(self, "key_id", "test-key")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "scopes", frozenset(scopes))
        object.__setattr__(self, "created_at", None)
        object.__setattr__(self, "expires_at", None)

    def has(self, scope: Scope) -> bool:
        return scope in self.scopes


@pytest.fixture
def mock_ctx() -> dict:
    return {
        "engine": MagicMock(),
        "builder": MagicMock(),
        "graph": MagicMock(),
        "vector_store": MagicMock(),
        "metrics": MagicMock(),
        "principal": MockPrincipal(),
        "correlation_id": "test-correlation-id",
    }


@pytest.fixture
def mock_handlers() -> dict:
    async def slow_handler(p: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(0.1)
        return {"status": "slow"}

    return {
        "smp/test/ok": AsyncMock(return_value={"status": "ok"}),
        "smp/test/error": AsyncMock(side_effect=Exception("Handler Error")),
        "smp/test/slow": AsyncMock(side_effect=slow_handler),
        "smp/test/invalid_params": AsyncMock(
            side_effect=lambda p, c: (
                # Simulate msgspec.convert failure
                exec('raise TypeError("Invalid parameter type")') if p.get("fail") else {"status": "ok"}
            )
        ),
    }


@pytest.mark.asyncio
class TestHandlerDispatchIsolation:
    """Tests for the _dispatch function in isolation."""

    async def test_dispatch_success(self, mock_ctx: dict, mock_handlers: dict) -> None:
        with patch("smp.protocol.server._HANDLERS", mock_handlers):
            params = {"key": "value"}
            result = await _dispatch("smp/test/ok", params, mock_ctx)
            assert result == {"status": "ok"}
            mock_handlers["smp/test/ok"].assert_called_once_with(params, mock_ctx)

    async def test_dispatch_method_not_found(self, mock_ctx: dict, mock_handlers: dict) -> None:
        with patch("smp.protocol.server._HANDLERS", mock_handlers):
            with pytest.raises(_MethodNotFoundError) as excinfo:
                await _dispatch("smp/unknown", {}, mock_ctx)
            assert excinfo.value.method == "smp/unknown"

    async def test_dispatch_handler_exception(self, mock_ctx: dict, mock_handlers: dict) -> None:
        with patch("smp.protocol.server._HANDLERS", mock_handlers):
            with pytest.raises(Exception) as excinfo:
                await _dispatch("smp/test/error", {}, mock_ctx)
            assert str(excinfo.value) == "Handler Error"

    @pytest.mark.parametrize("method", list(_HANDLERS.keys()))
    async def test_all_registered_handlers_resolvable(self, method: str, mock_ctx: dict) -> None:
        """Verify that every handler in the global registry can be resolved by _dispatch."""
        # We mock the actual handler to avoid needing full system setup
        with patch.dict("smp.protocol.server._HANDLERS", {method: AsyncMock(return_value="ok")}):
            result = await _dispatch(method, {}, mock_ctx)
            assert result == "ok"

    async def test_dispatch_params_passing(self, mock_ctx: dict, mock_handlers: dict) -> None:
        with patch("smp.protocol.server._HANDLERS", mock_handlers):
            complex_params = {
                "query": "test",
                "depth": 5,
                "filters": {"type": "node"},
                "tags": ["a", "b"],
            }
            await _dispatch("smp/test/ok", complex_params, mock_ctx)
            mock_handlers["smp/test/ok"].assert_called_once_with(complex_params, mock_ctx)

    async def test_dispatch_empty_params(self, mock_ctx: dict, mock_handlers: dict) -> None:
        with patch("smp.protocol.server._HANDLERS", mock_handlers):
            await _dispatch("smp/test/ok", {}, mock_ctx)
            mock_handlers["smp/test/ok"].assert_called_once_with({}, mock_ctx)


@pytest.mark.asyncio
class TestRpcEndpointIntegration:
    """Tests for the /rpc endpoint in the FastAPI app."""

    @pytest.fixture
    async def app(self):
        # Use a dummy auth policy to simplify authentication
        class OpenPolicy:
            max_request_bytes = 10 * 1024 * 1024
            rate_limit_per_minute = 1000
            open_mode = "open"

            def authenticate(self, token: str | None) -> Principal:
                return MockPrincipal()

        policy = OpenPolicy()
        # Patch MetricsRegistry so that create_app's closure uses a mock
        metrics_mock = MagicMock()
        with patch("smp.protocol.server.MetricsRegistry", return_value=metrics_mock):
            app = create_app(auth_policy=policy)

        # Manually populate state since lifespan doesn't run in AsyncClient by default
        app.state.graph = MagicMock()
        app.state.vector_store = MagicMock()
        app.state.engine = MagicMock()
        app.state.builder = MagicMock()
        app.state.metrics = metrics_mock
        app.state.auth_policy = policy
        app.state.rate_limiter = MagicMock()
        app.state.runtime_ctx = {
            "engine": app.state.engine,
            "builder": app.state.builder,
            "graph": app.state.graph,
            "vector_store": app.state.vector_store,
            "metrics": metrics_mock,
        }
        return app

    async def test_rpc_success(self, app, mock_handlers):
        with patch("smp.protocol.server._HANDLERS", mock_handlers):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                payload = {
                    "jsonrpc": "2.0",
                    "method": "smp/test/ok",
                    "params": {"foo": "bar"},
                    "id": "req-1",
                }
                response = await ac.post("/rpc", json=payload)
                assert response.status_code == 200
                data = response.json()
                assert data == {"jsonrpc": "2.0", "result": {"status": "ok"}, "id": "req-1"}

    async def test_rpc_method_not_found(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {
                "jsonrpc": "2.0",
                "method": "smp/unknown",
                "params": {},
                "id": "req-2",
            }
            response = await ac.post("/rpc", json=payload)
            assert response.status_code == 200
            data = response.json()
            assert data["error"]["code"] == -32601
            assert "Method not found" in data["error"]["message"]
            assert data["id"] == "req-2"

    async def test_rpc_parse_error(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # Send invalid JSON
            response = await ac.post("/rpc", content="invalid json")
            assert response.status_code == 200
            data = response.json()
            assert data["error"]["code"] == -32700
            assert data["error"]["message"] == "Parse error"

    async def test_rpc_invalid_request(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # Payload is not a dict
            response = await ac.post("/rpc", json=["not", "a", "dict"])
            assert response.status_code == 200
            data = response.json()
            assert data["error"]["code"] == -32600
            assert data["error"]["message"] == "Invalid request"

    async def test_rpc_missing_method(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {
                "jsonrpc": "2.0",
                "params": {},
                "id": "req-3",
            }
            response = await ac.post("/rpc", json=payload)
            assert response.status_code == 200
            data = response.json()
            assert data["error"]["code"] == -32600
            assert "Invalid request" in data["error"]["message"]

    async def test_rpc_handler_exception(self, app, mock_handlers):
        with patch("smp.protocol.server._HANDLERS", mock_handlers):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                payload = {
                    "jsonrpc": "2.0",
                    "method": "smp/test/error",
                    "params": {},
                    "id": "req-4",
                }
                response = await ac.post("/rpc", json=payload)
                assert response.status_code == 200
                data = response.json()
                # Internal errors are wrapped by safe_internal_error
                assert data["error"]["code"] == -32603
                assert data["id"] == "req-4"

    async def test_rpc_invalid_params_type(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # params should be a dict, but we send a list
            payload = {
                "jsonrpc": "2.0",
                "method": "smp/test/ok",
                "params": [1, 2, 3],
                "id": "req-5",
            }
            # We need a handler to be present
            with patch("smp.protocol.server._HANDLERS", {"smp/test/ok": AsyncMock(return_value="ok")}):
                response = await ac.post("/rpc", json=payload)
                assert response.status_code == 200
                data = response.json()
                assert data["result"] == "ok"  # params should have been coerced to {}

    async def test_rpc_params_none(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {
                "jsonrpc": "2.0",
                "method": "smp/test/ok",
                "params": None,
                "id": "req-6",
            }
            with patch("smp.protocol.server._HANDLERS", {"smp/test/ok": AsyncMock(return_value="ok")}):
                response = await ac.post("/rpc", json=payload)
                assert response.status_code == 200
                data = response.json()
                assert data["result"] == "ok"

    async def test_rpc_payload_too_large(self, app):
        # Override policy for this test
        app.state.auth_policy.max_request_bytes = 10
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {"jsonrpc": "2.0", "method": "smp/test/ok", "params": "too large"}
            response = await ac.post("/rpc", json=payload)
            assert response.status_code == 413
            data = response.json()
            assert data["error"]["code"] == -32600
            assert "Request body too large" in data["error"]["message"]

    async def test_rpc_latency_metrics(self, app, mock_handlers):
        with patch("smp.protocol.server._HANDLERS", mock_handlers):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                payload = {
                    "jsonrpc": "2.0",
                    "method": "smp/test/slow",
                    "params": {},
                    "id": "req-slow",
                }
                start = time.perf_counter()
                response = await ac.post("/rpc", json=payload)
                duration = time.perf_counter() - start

                assert response.status_code == 200
                assert duration >= 0.1
                # Since metrics is a closure variable, we check the state.metrics which is the same object
                app.state.metrics.observe.assert_called()
                # Check that smp_rpc_duration_seconds was observed
                args, kwargs = app.state.metrics.observe.call_args
                assert args[0] == "smp_rpc_duration_seconds"
                assert args[1] >= 0.1

    async def test_rpc_result_types(self, app):
        results = [
            {"dict": "value"},
            ["list", "of", "values"],
            "string result",
            123,
            True,
            None,
        ]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            for i, expected_result in enumerate(results):
                method = f"smp/test/res_{i}"
                with patch("smp.protocol.server._HANDLERS", {method: AsyncMock(return_value=expected_result)}):
                    payload = {
                        "jsonrpc": "2.0",
                        "method": method,
                        "params": {},
                        "id": f"req-{i}",
                    }
                    response = await ac.post("/rpc", json=payload)
                    assert response.status_code == 200
                    assert response.json()["result"] == expected_result

    async def test_rpc_empty_body(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/rpc", content="")
            assert response.status_code == 200
            data = response.json()
            assert data["error"]["code"] == -32700
            assert data["error"]["message"] == "Parse error"

    async def test_rpc_non_dict_payload(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/rpc", json="just a string")
            assert response.status_code == 200
            data = response.json()
            assert data["error"]["code"] == -32600
            assert data["error"]["message"] == "Invalid request"

    async def test_rpc_invalid_method_type(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {
                "jsonrpc": "2.0",
                "method": 123,
                "params": {},
                "id": "req-type",
            }
            response = await ac.post("/rpc", json=payload)
            assert response.status_code == 200
            data = response.json()
            assert data["error"]["code"] == -32600
            assert "Invalid request" in data["error"]["message"]

    async def test_rpc_empty_method_string(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {
                "jsonrpc": "2.0",
                "method": "",
                "params": {},
                "id": "req-empty",
            }
            response = await ac.post("/rpc", json=payload)
            assert response.status_code == 200
            data = response.json()
            assert data["error"]["code"] == -32600
            assert "Invalid request" in data["error"]["message"]

    async def test_rpc_metrics_increment(self, app, mock_handlers):
        with patch("smp.protocol.server._HANDLERS", mock_handlers):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                # Success case
                await ac.post("/rpc", json={"jsonrpc": "2.0", "method": "smp/test/ok", "params": {}, "id": 1})
                # Method not found case
                await ac.post("/rpc", json={"jsonrpc": "2.0", "method": "smp/unknown", "params": {}, "id": 2})
                # Error case
                await ac.post("/rpc", json={"jsonrpc": "2.0", "method": "smp/test/error", "params": {}, "id": 3})

                # Verify metrics calls
                metrics_calls = [call[0][0] for call in app.state.metrics.inc.call_args_list]
                assert "smp_rpc_requests_total" in metrics_calls
                assert "smp_rpc_errors_total" in metrics_calls

    async def test_rpc_correlation_id_passed(self, app, mock_handlers):
        with patch("smp.protocol.server._HANDLERS", mock_handlers):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                correlation_id = "my-custom-id"
                payload = {
                    "jsonrpc": "2.0",
                    "method": "smp/test/ok",
                    "params": {},
                    "id": "req-corr",
                }
                response = await ac.post("/rpc", json=payload, headers={"X-Correlation-ID": correlation_id})
                assert response.headers["X-Correlation-ID"] == correlation_id
                # Check that the correlation_id was passed in the context to the handler
                args, kwargs = mock_handlers["smp/test/ok"].call_args
                ctx = args[1]
                assert ctx["correlation_id"] == correlation_id

    async def test_rpc_principal_passed(self, app, mock_handlers):
        with patch("smp.protocol.server._HANDLERS", mock_handlers):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                payload = {
                    "jsonrpc": "2.0",
                    "method": "smp/test/ok",
                    "params": {},
                    "id": "req-princ",
                }
                await ac.post("/rpc", json=payload)
                args, kwargs = mock_handlers["smp/test/ok"].call_args
                ctx = args[1]
                assert isinstance(ctx["principal"], Principal)
                assert ctx["principal"].name == "test-user"

    async def test_rpc_params_coercion_failure_handling(self, app, mock_handlers):
        """Verify that when a handler fails during param coercion, it's caught as an internal error."""
        with patch("smp.protocol.server._HANDLERS", mock_handlers):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                payload = {
                    "jsonrpc": "2.0",
                    "method": "smp/test/invalid_params",
                    "params": {"fail": True},
                    "id": "req-coerce",
                }
                response = await ac.post("/rpc", json=payload)
                assert response.status_code == 200
                data = response.json()
                assert data["error"]["code"] == -32603
                assert data["id"] == "req-coerce"

    async def test_rpc_invalid_json_utf8(self, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # Send invalid utf-8 bytes
            response = await ac.post("/rpc", content=b"\xff\xfe\xfd")
            assert response.status_code == 200
            data = response.json()
            assert data["error"]["code"] == -32700
            assert data["error"]["message"] == "Parse error"
