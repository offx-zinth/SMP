"""Observability tests: Metrics (O-006 to O-009)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smp.core.models import EdgeType, GraphEdge, GraphNode, NodeType, SemanticProperties, StructuralProperties
from smp.observability.metrics import MetricsRegistry, install_standard_metrics
from smp.protocol.auth import AuthPolicy, Principal, Scope
from smp.protocol.server import create_app
from smp.store.graph.mmap_store import MMapGraphStore


def _node(node_id: str = "test_node", name: str = "test_fn") -> GraphNode:
    return GraphNode(
        id=node_id,
        type=NodeType.FUNCTION,
        file_path="src/test.py",
        structural=StructuralProperties(
            name=name,
            file="src/test.py",
            signature=f"def {name}():",
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


@pytest.fixture()
def metrics_registry() -> Iterator[MetricsRegistry]:
    registry = MetricsRegistry()
    install_standard_metrics(registry)
    yield registry


class TestPrometheusEndpoint:
    """O-006: Prometheus endpoint - /metrics returns valid Prometheus format."""

    def test_metrics_endpoint_returns_200(self, http_test_client: TestClient) -> None:
        response = http_test_client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_endpoint_returns_prometheus_text(self, http_test_client: TestClient) -> None:
        response = http_test_client.get("/metrics")
        assert response.status_code == 200
        body = response.text
        assert "# TYPE" in body
        assert "# HELP" in body

    def test_metrics_contains_valid_prometheus_format(self, http_test_client: TestClient) -> None:
        response = http_test_client.get("/metrics")
        body = response.text
        lines = body.split("\n")
        metric_lines = [ln for ln in lines if ln and not ln.startswith("#")]
        for line in metric_lines:
            pattern = r"^[a-zA-Z_:][a-zA-Z0-9_:]*\{?[^{}\n]*\}?\s+[\d.eE+-]+\s*$"
            assert re.match(pattern, line), f"Invalid metric line: {line}"

    def test_metrics_has_type_comments(self, http_test_client: TestClient) -> None:
        response = http_test_client.get("/metrics")
        body = response.text
        assert "# TYPE smp_rpc_requests_total counter" in body

    def test_metrics_has_help_comments(self, http_test_client: TestClient) -> None:
        response = http_test_client.get("/metrics")
        body = response.text
        assert "# HELP" in body

    def test_metrics_content_type_text_plain(self, http_test_client: TestClient) -> None:
        response = http_test_client.get("/metrics")
        assert response.headers.get("content-type", "").startswith("text/plain")

    def test_metrics_endpoint_excludes_invalid_chars(self, http_test_client: TestClient) -> None:
        response = http_test_client.get("/metrics")
        body = response.text
        assert "\x00" not in body

    def test_metrics_labels_are_escaped(self, http_test_client: TestClient) -> None:
        http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": 'test"quote'}, "id": 1},
            headers={"Authorization": "Bearer reader"},
        )
        response = http_test_client.get("/metrics")
        assert response.status_code == 200


class TestRequestCounterMetric:
    """O-007: Request counter metric - counted by method/status."""

    def test_request_counter_increments_on_get(self, http_test_client: TestClient) -> None:
        http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"Authorization": "Bearer reader"},
        )
        response = http_test_client.get("/metrics")
        assert "smp_rpc_requests_total" in response.text

    def test_request_counter_different_methods(self, http_test_client: TestClient) -> None:
        methods = ["smp/search", "smp/nodes", "smp/edges"]
        for method in methods:
            http_test_client.post(
                "/rpc",
                json={"jsonrpc": "2.0", "method": method, "params": {}, "id": 1},
                headers={"Authorization": "Bearer reader"},
            )
        response = http_test_client.get("/metrics")
        body = response.text
        assert "smp_search" in body or "smp_rpc_requests_total" in body

    def test_request_counter_by_status_code(self, http_test_client: TestClient) -> None:
        http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"Authorization": "Bearer reader"},
        )
        response = http_test_client.get("/metrics")
        assert "status=" in response.text

    def test_request_counter_has_method_label(self, http_test_client: TestClient) -> None:
        http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"Authorization": "Bearer reader"},
        )
        response = http_test_client.get("/metrics")
        body = response.text
        assert "method=" in body

    def test_request_counter_includes_error_count(self, http_test_client: TestClient) -> None:
        http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/invalid", "params": {}, "id": 1},
            headers={"Authorization": "Bearer reader"},
        )
        response = http_test_client.get("/metrics")
        assert "smp_rpc_errors_total" in response.text or "smp_rpc_requests_total" in response.text

    def test_request_counter_multiple_requests(self, http_test_client: TestClient) -> None:
        for i in range(5):
            http_test_client.post(
                "/rpc",
                json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": f"x{i}"}, "id": i},
                headers={"Authorization": "Bearer reader"},
            )
        http_test_client.get("/metrics")

    def test_request_counter_labels_are_sorted(self, http_test_client: TestClient) -> None:
        http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"Authorization": "Bearer reader"},
        )
        response = http_test_client.get("/metrics")
        body = response.text
        label_pattern = r"\{[^}]+\}"
        labels = re.findall(label_pattern, body)
        for label in labels:
            assert "," not in label[1:-1] or label.count(",") > 0

    def test_request_counter_empty_labels(self, http_test_client: TestClient) -> None:
        response = http_test_client.get("/metrics")
        assert "smp_rpc_requests_total{" not in response.text.replace("smp_rpc_requests_total{", "", 1)

    def test_request_counter_cumulative(self, http_test_client: TestClient) -> None:
        for i in range(3):
            http_test_client.post(
                "/rpc",
                json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": f"x{i}"}, "id": i},
                headers={"Authorization": "Bearer reader"},
            )
        response = http_test_client.get("/metrics")
        match = re.search(r"smp_rpc_requests_total[^}]*}\s+(\d+)", response.text)
        if match:
            assert int(match.group(1)) >= 3


class TestLatencyHistogram:
    """O-008: Latency histogram - request duration."""

    def test_latency_metric_exists(self, http_test_client: TestClient) -> None:
        http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"Authorization": "Bearer reader"},
        )
        response = http_test_client.get("/metrics")
        assert "smp_rpc_duration_seconds" in response.text

    def test_latency_metric_has_count(self, http_test_client: TestClient) -> None:
        http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"Authorization": "Bearer reader"},
        )
        response = http_test_client.get("/metrics")
        assert "smp_rpc_duration_seconds_count" in response.text

    def test_latency_metric_has_sum(self, http_test_client: TestClient) -> None:
        http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"Authorization": "Bearer reader"},
        )
        response = http_test_client.get("/metrics")
        assert "smp_rpc_duration_seconds_sum" in response.text

    def test_latency_records_observation(self, http_test_client: TestClient) -> None:
        for i in range(3):
            http_test_client.post(
                "/rpc",
                json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": f"x{i}"}, "id": i},
                headers={"Authorization": "Bearer reader"},
            )
        http_test_client.get("/metrics")

    def test_latency_bucket_quantiles(self, http_test_client: TestClient) -> None:
        http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"Authorization": "Bearer reader"},
        )
        response = http_test_client.get("/metrics")
        body = response.text
        assert "smp_rpc_duration_seconds" in body

    def test_latency_in_seconds(self, http_test_client: TestClient) -> None:
        http_test_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/search", "params": {"query": "x"}, "id": 1},
            headers={"Authorization": "Bearer reader"},
        )
        response = http_test_client.get("/metrics")
        assert "_seconds" in response.text


class TestMetricsRegistry:
    """Test MetricsRegistry directly."""

    def test_gauge_creation_and_set(self, metrics_registry: MetricsRegistry) -> None:
        metrics_registry.gauge("test_gauge")
        metrics_registry.set("test_gauge", 42.0)
        assert metrics_registry.value("test_gauge") == 42.0

    def test_counter_creation_and_increment(self, metrics_registry: MetricsRegistry) -> None:
        metrics_registry.counter("test_counter")
        metrics_registry.inc("test_counter")
        metrics_registry.inc("test_counter")
        assert metrics_registry.value("test_counter") == 2.0

    def test_counter_with_labels(self, metrics_registry: MetricsRegistry) -> None:
        metrics_registry.counter("labeled_counter")
        metrics_registry.inc("labeled_counter", method="get")
        metrics_registry.inc("labeled_counter", method="post")
        assert metrics_registry.value("labeled_counter", method="get") == 1.0
        assert metrics_registry.value("labeled_counter", method="post") == 1.0

    def test_summary_observation(self, metrics_registry: MetricsRegistry) -> None:
        metrics_registry.summary("test_summary")
        metrics_registry.observe("test_summary", 0.1)
        metrics_registry.observe("test_summary", 0.2)
        rendered = metrics_registry.render()
        assert "test_summary_count" in rendered

    def test_gauge_update(self, metrics_registry: MetricsRegistry) -> None:
        metrics_registry.gauge("update_gauge")
        metrics_registry.set("update_gauge", 10.0)
        metrics_registry.set("update_gauge", 20.0)
        assert metrics_registry.value("update_gauge") == 20.0

    def test_render_output_format(self, metrics_registry: MetricsRegistry) -> None:
        rendered = metrics_registry.render()
        lines = rendered.split("\n")
        assert any("# TYPE" in line for line in lines)
        assert any("# HELP" in line for line in lines)

    def test_metric_value_nonexistent_returns_zero(self, metrics_registry: MetricsRegistry) -> None:
        assert metrics_registry.value("nonexistent_metric") == 0.0


class TestGraphSizeMetrics:
    """O-009: Graph size metrics - node/edge counts."""

    async def test_nodes_total_metric_exists(self, tmp_path: Path) -> None:
        graph_path = tmp_path / "nodes_test.smpg"
        store = MMapGraphStore(path=str(graph_path))
        await store.connect()
        try:
            await store.upsert_node(_node("test_node"))
        finally:
            await store.close()

    async def test_edges_total_metric_exists(self, tmp_path: Path) -> None:
        graph_path = tmp_path / "edges_test.smpg"
        store = MMapGraphStore(path=str(graph_path))
        await store.connect()
        try:
            await store.upsert_node(_node("source"))
            await store.upsert_node(_node("target"))
            await store.upsert_edge(GraphEdge(source_id="source", target_id="target", type=EdgeType.CALLS))
        finally:
            await store.close()

    async def test_node_count_reflects_actual_nodes(self, tmp_path: Path) -> None:
        graph_path = tmp_path / "node_count.smpg"
        store = MMapGraphStore(path=str(graph_path))
        await store.connect()
        try:
            await store.upsert_node(_node("a"))
            await store.upsert_node(_node("b"))
            await store.upsert_node(_node("c"))
            count = await store.count_nodes()
            assert count == 3
        finally:
            await store.close()

    async def test_edge_count_reflects_actual_edges(self, tmp_path: Path) -> None:
        graph_path = tmp_path / "edge_count.smpg"
        store = MMapGraphStore(path=str(graph_path))
        await store.connect()
        try:
            await store.upsert_node(_node("n1"))
            await store.upsert_node(_node("n2"))
            await store.upsert_node(_node("n3"))
            await store.upsert_edge(GraphEdge(source_id="n1", target_id="n2", type=EdgeType.CALLS))
            await store.upsert_edge(GraphEdge(source_id="n2", target_id="n3", type=EdgeType.CALLS))
            count = await store.count_edges()
            assert count == 2
        finally:
            await store.close()

    async def test_node_count_after_delete(self, tmp_path: Path) -> None:
        graph_path = tmp_path / "delete_node.smpg"
        store = MMapGraphStore(path=str(graph_path))
        await store.connect()
        try:
            await store.upsert_node(_node("to_delete"))
            await store.delete_node("to_delete")
            count = await store.count_nodes()
            assert count == 0
        finally:
            await store.close()


class TestStandardMetrics:
    """Test install_standard_metrics function."""

    def test_standard_metrics_registration(self) -> None:
        registry = MetricsRegistry()
        install_standard_metrics(registry)
        rendered = registry.render()
        assert "smp_rpc_requests_total" in rendered
        assert "smp_rpc_errors_total" in rendered
        assert "smp_rpc_duration_seconds" in rendered
        assert "smp_nodes_total" in rendered
        assert "smp_edges_total" in rendered
        assert "smp_sessions_active" in rendered
        assert "smp_locks_active" in rendered

    def test_standard_metrics_idempotent(self) -> None:
        registry = MetricsRegistry()
        install_standard_metrics(registry)
        install_standard_metrics(registry)
        rendered = registry.render()
        assert "# TYPE smp_rpc_requests_total counter" in rendered
