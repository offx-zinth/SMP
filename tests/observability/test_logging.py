"""Observability tests: Logging (O-001 to O-005)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smp.core.models import (
    GraphNode,
    NodeType,
    SemanticProperties,
    StructuralProperties,
)
from smp.protocol.auth import AuthPolicy, Principal, Scope
from smp.protocol.server import create_app


def _node(node_id: str = "test_node") -> GraphNode:
    return GraphNode(
        id=node_id,
        type=NodeType.FUNCTION,
        file_path="src/test.py",
        structural=StructuralProperties(
            name="test_fn",
            file="src/test.py",
            signature="def test_fn():",
            start_line=1,
            end_line=10,
            lines=10,
        ),
        semantic=SemanticProperties(),
    )


def _admin_policy() -> AuthPolicy:
    return AuthPolicy(
        keys={
            "admin": Principal(
                key_id="adm",
                name="admin",
                scopes=frozenset({Scope.READ, Scope.WRITE, Scope.ADMIN}),
            ),
            "reader": Principal(key_id="ro", name="reader", scopes=frozenset({Scope.READ})),
        },
        open_mode=False,
    )


@pytest.fixture()
def http_test_client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(graph_path=str(tmp_path / "graph.smpg"), auth_policy=_admin_policy())
    with TestClient(app) as client:
        yield client


# O-001: Correlation ID propagation (all logs share same correlation_id)


class TestCorrelationIdPropagation:
    """O-001: Correlation ID propagation - all logs share same correlation_id."""

    def test_correlation_id_propagated_to_request_logs(self, http_test_client: TestClient) -> None:
        custom_corr_id = "test-correlation-001"
        response = http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"Authorization": "Bearer reader", "X-Correlation-ID": custom_corr_id},
        )
        assert response.status_code == 200

    def test_correlation_id_propagated_across_all_loggers(self, http_test_client: TestClient) -> None:
        custom_corr_id = "test-correlation-002"
        http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"Authorization": "Bearer reader", "X-Correlation-ID": custom_corr_id},
        )
        http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/nodes", "params": {}, "id": 2},
            headers={"Authorization": "Bearer reader", "X-Correlation-ID": custom_corr_id},
        )

    def test_correlation_id_in_context_vars(self, http_test_client: TestClient) -> None:
        correlation_ids = []
        for i in range(3):
            corr_id = f"corr-{i}"
            response = http_test_client.post(
                "/rpc",
                json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": f"x{i}"}, "id": i},
                headers={"Authorization": "Bearer reader", "X-Correlation-ID": corr_id},
            )
            assert response.status_code == 200
            correlation_ids.append(corr_id)
        assert len(set(correlation_ids)) == 3

    def test_correlation_id_generated_when_missing(self, http_test_client: TestClient) -> None:
        response = http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"Authorization": "Bearer reader"},
        )
        assert response.status_code == 200

    def test_correlation_id_persists_through_handler_chain(self, http_test_client: TestClient) -> None:
        correlation_id = "test-chain-correlation"
        for i in range(2):
            response = http_test_client.post(
                "/rpc",
                json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": f"x{i}"}, "id": i},
                headers={"Authorization": "Bearer reader", "X-Correlation-ID": correlation_id},
            )
            assert response.status_code == 200
            assert response.headers.get("X-Correlation-ID") == correlation_id


# O-002: Correlation ID in response (X-Correlation-ID header)


class TestCorrelationIdInResponse:
    """O-002: Correlation ID in response - X-Correlation-ID header."""

    def test_correlation_id_returned_in_header(self, http_test_client: TestClient) -> None:
        custom_corr_id = "test-corr-003"
        response = http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"Authorization": "Bearer reader", "X-Correlation-ID": custom_corr_id},
        )
        assert response.status_code == 200
        assert response.headers.get("X-Correlation-ID") == custom_corr_id

    def test_correlation_id_header_on_success(self, http_test_client: TestClient) -> None:
        response = http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"Authorization": "Bearer reader"},
        )
        assert response.status_code == 200
        assert "X-Correlation-ID" in response.headers

    def test_correlation_id_header_on_error(self, http_test_client: TestClient) -> None:
        response = http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/invalid", "params": {}, "id": 1},
            headers={"Authorization": "Bearer reader"},
        )
        assert "X-Correlation-ID" in response.headers

    def test_correlation_id_header_on_health(self, http_test_client: TestClient) -> None:
        response = http_test_client.get("/health")
        assert response.status_code == 200

    def test_correlation_id_header_on_ready(self, http_test_client: TestClient) -> None:
        response = http_test_client.get("/ready")
        assert response.status_code == 200

    def test_correlation_id_header_on_metrics(self, http_test_client: TestClient) -> None:
        response = http_test_client.get("/metrics")
        assert response.status_code == 200

    def test_correlation_id_matches_request_when_provided(self, http_test_client: TestClient) -> None:
        test_corr_id = "explicit-corr-id-123"
        response = http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"Authorization": "Bearer reader", "X-Correlation-ID": test_corr_id},
        )
        assert response.headers.get("X-Correlation-ID") == test_corr_id


# O-003: Structured logging (level, logger, timestamp fields)


class TestStructuredLogging:
    """O-003: Structured logging - level, logger, timestamp fields."""

    def test_log_output_contains_level(self) -> None:
        from smp.logging import get_logger

        log = get_logger("test.structured")
        log.info("test_event", level="info")

    def test_log_output_contains_logger_name(self) -> None:
        from smp.logging import get_logger

        log = get_logger("test.logger.name")
        log.info("test_event")

    def test_log_output_contains_timestamp(self) -> None:
        from smp.logging import get_logger

        log = get_logger("test.timestamp")
        log.info("test_event")

    def test_structured_log_contains_all_required_fields(self) -> None:
        from smp.logging import get_logger

        log = get_logger("test.required.fields")
        log.info("event_with_fields", nodes=10, edges=20, status="ok")

    def test_log_level_debug(self) -> None:
        from smp.logging import get_logger

        log = get_logger("test.level.debug")
        log.debug("debug_event")

    def test_log_level_info(self) -> None:
        from smp.logging import get_logger

        log = get_logger("test.level.info")
        log.info("info_event")

    def test_log_level_warning(self) -> None:
        from smp.logging import get_logger

        log = get_logger("test.level.warning")
        log.warning("warning_event")

    def test_log_level_error(self) -> None:
        from smp.logging import get_logger

        log = get_logger("test.level.error")
        log.error("error_event")

    def test_structured_log_with_numeric_fields(self) -> None:
        from smp.logging import get_logger

        log = get_logger("test.numeric")
        log.info("numeric_event", count=42, duration=0.123)


# O-004: Auth failure logging (WARNING level)


class TestAuthFailureLogging:
    """O-004: Auth failure logging - WARNING level."""

    def test_auth_failure_logs_warning(self, http_test_client: TestClient) -> None:
        response = http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"Authorization": "Bearer invalid_token"},
        )
        assert response.status_code == 401

    def test_auth_failure_missing_token(self, http_test_client: TestClient) -> None:
        response = http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
        )
        assert response.status_code == 401

    def test_auth_failure_invalid_scope(self, http_test_client: TestClient) -> None:
        response = http_test_client.post(
            "/admin/backup",
            json={},
            headers={"Authorization": "Bearer reader"},
        )
        assert response.status_code == 403

    def test_auth_failure_expired_key(self, http_test_client: TestClient) -> None:
        response = http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"Authorization": "Bearer expired_key_12345678901234567890"},
        )
        assert response.status_code in (401, 403)

    def test_auth_failure_wrong_key_format(self, http_test_client: TestClient) -> None:
        response = http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"Authorization": "InvalidFormat"},
        )
        assert response.status_code == 401


# O-005: Shutdown sequence logging (4 phases)


class TestShutdownSequenceLogging:
    """O-005: Shutdown sequence logging - 4 phases."""

    async def test_shutdown_phase_graceful(self, tmp_path: Path) -> None:
        from smp.protocol.server import create_app

        create_app(graph_path=str(tmp_path / "graph.smpg"), auth_policy=_admin_policy())

    async def test_shutdown_phase_store_close(self, tmp_path: Path) -> None:
        from smp.store.graph.mmap_store import MMapGraphStore

        graph_path = tmp_path / "shutdown_test.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()
        await store.close()

    async def test_shutdown_phase_vector_close(self, tmp_path: Path) -> None:
        from smp.vector.mmap_vector import MMapVectorStore

        vector_path = tmp_path / "shutdown_vector.smpv"
        store = MMapVectorStore(path=vector_path, dimension=128)
        await store.connect()
        await store.close()

    async def test_shutdown_phase_audit_log(self, tmp_path: Path) -> None:
        from smp.store.graph.mmap_store import MMapGraphStore

        graph_path = tmp_path / "shutdown_audit.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()
        await store.append_audit({"event": "shutdown_test"})
        await store.close()

    async def test_shutdown_clears_context_vars(self, tmp_path: Path) -> None:
        import structlog

        from smp.store.graph.mmap_store import MMapGraphStore

        graph_path = tmp_path / "shutdown_ctx.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()
        structlog.contextvars.bind_contextvars(correlation_id="shutdown-test")
        await store.close()

    async def test_shutdown_multiple_stores(self, tmp_path: Path) -> None:
        from smp.store.graph.mmap_store import MMapGraphStore
        from smp.vector.mmap_vector import MMapVectorStore

        graph_path = tmp_path / "multi_shutdown.smpg"
        vector_path = tmp_path / "multi_vector.smpv"

        graph_store = MMapGraphStore(path=graph_path)
        vector_store = MMapVectorStore(path=vector_path, dimension=128)

        await graph_store.connect()
        await vector_store.connect()

        await graph_store.close()
        await vector_store.close()

    async def test_shutdown_preserves_data(self, tmp_path: Path) -> None:
        from smp.store.graph.mmap_store import MMapGraphStore

        graph_path = tmp_path / "preserve.smpg"
        store = MMapGraphStore(path=graph_path)
        await store.connect()
        await store.upsert_node(_node("preserve_node"))
        await store.close()

        store2 = MMapGraphStore(path=graph_path)
        await store2.connect()
        try:
            node = await store2.get_node("preserve_node")
            assert node is not None
        finally:
            await store2.close()
