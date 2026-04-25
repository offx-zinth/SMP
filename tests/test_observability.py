"""Phase 6 tests: observability, backup/restore, compaction, admin endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smp.core.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    SemanticProperties,
    StructuralProperties,
)
from smp.observability.backup import backup, compact, restore
from smp.observability.metrics import MetricsRegistry, install_standard_metrics
from smp.protocol.auth import AuthPolicy, Principal, Scope
from smp.protocol.server import create_app
from smp.store.graph.mmap_store import MMapGraphStore


def _node(node_id: str, name: str = "fn") -> GraphNode:
    return GraphNode(
        id=node_id,
        type=NodeType.FUNCTION,
        file_path="src/x.py",
        structural=StructuralProperties(name=name, file="src/x.py", signature=f"def {name}():", start_line=1),
        semantic=SemanticProperties(),
    )


# ---------------------------------------------------------------------------
# Metrics registry
# ---------------------------------------------------------------------------


class TestMetricsRegistry:
    def test_counter_increments(self) -> None:
        m = MetricsRegistry()
        m.counter("requests")
        m.inc("requests", method="get")
        m.inc("requests", method="get")
        m.inc("requests", method="post")
        assert m.value("requests", method="get") == 2.0
        assert m.value("requests", method="post") == 1.0

    def test_gauge_set(self) -> None:
        m = MetricsRegistry()
        m.gauge("nodes")
        m.set("nodes", 42)
        assert m.value("nodes") == 42.0
        m.set("nodes", 7)
        assert m.value("nodes") == 7.0

    def test_summary_observation(self) -> None:
        m = MetricsRegistry()
        m.summary("latency")
        m.observe("latency", 0.1, method="get")
        m.observe("latency", 0.3, method="get")
        rendered = m.render()
        assert "latency_count" in rendered
        assert "latency_sum" in rendered
        assert 'method="get"' in rendered

    def test_render_includes_help_and_type(self) -> None:
        m = MetricsRegistry()
        m.counter("requests", help="Total requests")
        m.inc("requests")
        rendered = m.render()
        assert "# HELP requests Total requests" in rendered
        assert "# TYPE requests counter" in rendered
        assert "requests 1" in rendered

    def test_label_escaping(self) -> None:
        m = MetricsRegistry()
        m.counter("x")
        m.inc("x", method='quoted "value"')
        rendered = m.render()
        assert '\\"value\\"' in rendered

    def test_install_standard_metrics_is_idempotent(self) -> None:
        m = MetricsRegistry()
        install_standard_metrics(m)
        install_standard_metrics(m)
        rendered = m.render()
        assert "smp_rpc_requests_total" in rendered
        assert "smp_uptime_seconds" in rendered


# ---------------------------------------------------------------------------
# Backup / restore / compact
# ---------------------------------------------------------------------------


class TestBackupRestore:
    async def test_backup_produces_readable_copy(self, tmp_path: Path) -> None:
        path = tmp_path / "live.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_nodes([_node("a"), _node("b")])
        await store.upsert_edge(GraphEdge(source_id="a", target_id="b", type=EdgeType.CALLS))

        snapshot = tmp_path / "snap.smpg"
        await backup(store, snapshot)
        await store.close()

        clone = MMapGraphStore(snapshot)
        await clone.connect()
        try:
            assert await clone.count_nodes() == 2
            assert await clone.count_edges() == 1
        finally:
            await clone.close()

    async def test_restore_replaces_target(self, tmp_path: Path) -> None:
        live = tmp_path / "live.smpg"
        bad = tmp_path / "bad.smpg"

        store = MMapGraphStore(live)
        await store.connect()
        await store.upsert_node(_node("a"))
        await backup(store, bad)
        await store.upsert_node(_node("b"))
        assert await store.count_nodes() == 2
        await store.close()

        # Restore the older snapshot
        await restore(live, bad)

        # Re-open the store and confirm we're back at 1 node
        store2 = MMapGraphStore(live)
        await store2.connect()
        try:
            assert await store2.count_nodes() == 1
            assert await store2.get_node("a") is not None
            assert await store2.get_node("b") is None
        finally:
            await store2.close()

    async def test_restore_writes_sidecar(self, tmp_path: Path) -> None:
        live = tmp_path / "live.smpg"
        snap = tmp_path / "snap.smpg"

        store = MMapGraphStore(live)
        await store.connect()
        await store.upsert_node(_node("a"))
        await backup(store, snap)
        await store.upsert_node(_node("b"))
        await store.close()

        await restore(live, snap)

        backups = list(tmp_path.glob("live.smpg.bak.*"))
        assert backups, "expected a sidecar backup of the prior live file"


class TestCompact:
    async def test_compact_removes_redundancy(self, tmp_path: Path) -> None:
        path = tmp_path / "live.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        # Update the same node many times to bloat the journal
        for i in range(50):
            updated = _node("a", name=f"v{i}")
            await store.upsert_node(updated)
        size_before = store.file.size
        stats = await compact(store)
        try:
            assert stats["before_bytes"] == size_before
            assert stats["after_bytes"] <= size_before
            assert await store.count_nodes() == 1
            node = await store.get_node("a")
            assert node is not None
            assert node.structural.name == "v49"
        finally:
            await store.close()

    async def test_compact_preserves_sessions_and_locks(self, tmp_path: Path) -> None:
        path = tmp_path / "live.smpg"
        store = MMapGraphStore(path)
        await store.connect()
        await store.upsert_session({"session_id": "s1", "agent": "a"})
        await store.upsert_lock("a.py", "s1")
        await store.append_audit({"event": "noop"})
        await compact(store)
        try:
            assert await store.get_session("s1") is not None
            assert await store.get_lock("a.py") is not None
            audit = await store.list_audit()
            assert any(e.get("event") == "noop" for e in audit)
        finally:
            await store.close()


# ---------------------------------------------------------------------------
# HTTP endpoints (/health, /ready, /metrics, /admin/backup, /admin/compact)
# ---------------------------------------------------------------------------


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
def http(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(graph_path=str(tmp_path / "graph.smpg"), auth_policy=_admin_policy())
    with TestClient(app) as client:
        yield client


class TestHealthAndReady:
    def test_health_is_public(self, http: TestClient) -> None:
        assert http.get("/health").status_code == 200

    def test_ready_returns_200_when_store_open(self, http: TestClient) -> None:
        assert http.get("/ready").status_code == 200


class TestMetricsEndpoint:
    def test_metrics_returns_prometheus_text(self, http: TestClient) -> None:
        # Drive at least one RPC so the request counter is non-empty.
        ok = http.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"Authorization": "Bearer reader"},
        )
        assert ok.status_code == 200
        response = http.get("/metrics")
        assert response.status_code == 200
        body = response.text
        assert "# TYPE smp_rpc_requests_total counter" in body
        assert "smp_rpc_requests_total" in body
        assert "smp_nodes_total" in body
        assert "smp_uptime_seconds" in body

    def test_metrics_record_failures(self, http: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        from smp.protocol import server as server_module

        async def bomb(*_, **__):  # type: ignore[no-untyped-def]
            raise ValueError("boom")

        monkeypatch.setitem(server_module._HANDLERS, "smp/search", bomb)

        bad = http.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"Authorization": "Bearer reader"},
        )
        assert bad.status_code == 200
        body = http.get("/metrics").text
        assert "smp_rpc_errors_total" in body


class TestAdminEndpoints:
    def test_backup_requires_admin(self, http: TestClient, tmp_path: Path) -> None:
        target = tmp_path / "snapshot.smpg"
        no_auth = http.post("/admin/backup", json={"target": str(target)})
        assert no_auth.status_code == 401

        forbidden = http.post(
            "/admin/backup",
            json={"target": str(target)},
            headers={"Authorization": "Bearer reader"},
        )
        assert forbidden.status_code == 403

        ok = http.post(
            "/admin/backup",
            json={"target": str(target)},
            headers={"Authorization": "Bearer admin"},
        )
        assert ok.status_code == 200
        assert target.exists()

    def test_backup_rejects_missing_target(self, http: TestClient) -> None:
        response = http.post(
            "/admin/backup",
            json={},
            headers={"Authorization": "Bearer admin"},
        )
        assert response.status_code == 400

    def test_compact_requires_admin(self, http: TestClient) -> None:
        response = http.post(
            "/admin/compact",
            headers={"Authorization": "Bearer reader"},
        )
        assert response.status_code == 403

        ok = http.post(
            "/admin/compact",
            headers={"Authorization": "Bearer admin"},
        )
        assert ok.status_code == 200
        body = ok.json()
        assert body["compacted"] is True
        assert "before_bytes" in body and "after_bytes" in body
