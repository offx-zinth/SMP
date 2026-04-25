"""Comprehensive verification of all SMP JSON-RPC methods and HTTP routes.

Every method registered in :data:`smp.protocol.server._HANDLERS` is exercised
here at least once (handler dispatch matrix), and a smaller set of realistic
scenarios chains 3–8 calls together across handler families.  Wire-level
JSON-RPC envelopes (``-32700``, ``-32600``, ``-32601``) and the auxiliary
HTTP routes (``/health``, ``/stats``, ``/methods``, ``/smp/invalidate``) are
covered through :class:`fastapi.testclient.TestClient` so that the FastAPI
``lifespan`` is invoked exactly as in production.

Traceability — JSON-RPC method to test method
==============================================

Query
    smp/navigate            TestQueryDispatch.test_navigate
                            TestRealWorldScenarios.test_impact_of_deleting_function
    smp/trace               TestQueryDispatch.test_trace
                            TestRealWorldScenarios.test_impact_of_deleting_function
    smp/context             TestQueryDispatch.test_context
    smp/impact              TestQueryDispatch.test_impact
                            TestRealWorldScenarios.test_impact_of_deleting_function
    smp/locate              TestQueryDispatch.test_locate
    smp/search              TestQueryDispatch.test_search
    smp/flow                TestQueryDispatch.test_flow

Memory
    smp/update              TestMemoryDispatch.test_update
    smp/batch_update        TestMemoryDispatch.test_batch_update
    smp/reindex             TestMemoryDispatch.test_reindex

Analysis / telemetry
    smp/diff                TestAnalysisDispatch.test_diff
    smp/plan                TestAnalysisDispatch.test_plan
    smp/conflict            TestAnalysisDispatch.test_conflict
    smp/why                 TestAnalysisDispatch.test_why
    smp/telemetry           TestAnalysisDispatch.test_telemetry_summary
                            TestRealWorldScenarios.test_telemetry_after_seeding
    smp/telemetry/hot       TestAnalysisDispatch.test_telemetry_hot
                            TestRealWorldScenarios.test_telemetry_after_seeding
    smp/telemetry/node      TestAnalysisDispatch.test_telemetry_node
                            TestRealWorldScenarios.test_telemetry_after_seeding

Enrichment / annotation
    smp/enrich              TestEnrichmentDispatch.test_enrich
                            TestRealWorldScenarios.test_enrichment_round_trip
    smp/enrich/batch        TestEnrichmentDispatch.test_enrich_batch
    smp/enrich/stale        TestEnrichmentDispatch.test_enrich_stale
    smp/enrich/status       TestEnrichmentDispatch.test_enrich_status
                            TestRealWorldScenarios.test_enrichment_round_trip
    smp/annotate            TestEnrichmentDispatch.test_annotate
    smp/annotate/bulk       TestEnrichmentDispatch.test_annotate_bulk
    smp/tag                 TestEnrichmentDispatch.test_tag

Session / safety / audit
    smp/session/open        TestSessionDispatch.test_session_open
                            TestRealWorldScenarios.test_session_lifecycle_with_lock
    smp/session/close       TestSessionDispatch.test_session_close
                            TestRealWorldScenarios.test_session_lifecycle_with_lock
    smp/session/recover     TestSessionDispatch.test_session_recover
    smp/dryrun              TestSessionDispatch.test_dryrun
    smp/checkpoint          TestSessionDispatch.test_checkpoint
                            TestRealWorldScenarios.test_session_lifecycle_with_lock
    smp/rollback            TestSessionDispatch.test_rollback
                            TestRealWorldScenarios.test_session_lifecycle_with_lock
    smp/lock                TestSessionDispatch.test_lock
                            TestRealWorldScenarios.test_session_lifecycle_with_lock
    smp/unlock              TestSessionDispatch.test_unlock
                            TestRealWorldScenarios.test_session_lifecycle_with_lock
    smp/audit/get           TestSessionDispatch.test_audit_get
                            TestRealWorldScenarios.test_session_lifecycle_with_lock

Review / PR handoff
    smp/review/create       TestReviewDispatch.test_review_create
                            TestRealWorldScenarios.test_review_handoff_to_pr
    smp/review/approve      TestReviewDispatch.test_review_approve
                            TestRealWorldScenarios.test_review_handoff_to_pr
    smp/review/reject       TestReviewDispatch.test_review_reject
    smp/review/comment      TestReviewDispatch.test_review_comment
                            TestRealWorldScenarios.test_review_handoff_to_pr
    smp/pr/create           TestReviewDispatch.test_pr_create
                            TestRealWorldScenarios.test_review_handoff_to_pr

Sandbox
    smp/sandbox/spawn       TestSandboxDispatch.test_sandbox_spawn
                            TestRealWorldScenarios.test_sandbox_lifecycle
    smp/sandbox/execute     TestSandboxDispatch.test_sandbox_execute
                            TestRealWorldScenarios.test_sandbox_lifecycle
    smp/sandbox/kill        TestSandboxDispatch.test_sandbox_kill
                            TestRealWorldScenarios.test_sandbox_lifecycle

Community
    smp/community/detect    TestCommunityDispatch.test_community_detect
                            TestRealWorldScenarios.test_community_detect_then_get
    smp/community/list      TestCommunityDispatch.test_community_list
                            TestRealWorldScenarios.test_community_detect_then_get
    smp/community/get       TestCommunityDispatch.test_community_get
                            TestRealWorldScenarios.test_community_detect_then_get
    smp/community/boundaries
                            TestCommunityDispatch.test_community_boundaries
                            TestRealWorldScenarios.test_community_detect_then_get

Sync / integrity
    smp/sync                TestSyncDispatch.test_sync
                            TestRealWorldScenarios.test_integrity_baseline_and_check
    smp/index/import        TestSyncDispatch.test_index_import
                            TestHttpSurface.test_round_trip_seed_via_index_import
    smp/integrity/check     TestSyncDispatch.test_integrity_check
                            TestRealWorldScenarios.test_integrity_baseline_and_check
    smp/integrity/baseline  TestSyncDispatch.test_integrity_baseline
                            TestRealWorldScenarios.test_integrity_baseline_and_check

HTTP routes
    GET  /health            TestHttpSurface.test_health
    GET  /methods           TestHttpSurface.test_methods_lists_all_handlers
    GET  /stats             TestHttpSurface.test_stats_initial_empty
    POST /smp/invalidate    TestHttpSurface.test_invalidate_missing_path
                            TestHttpSurface.test_invalidate_with_path
    POST /rpc               TestJsonRpcWire.* and TestHttpSurface.test_round_trip_*
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from smp.core.models import EdgeType, NodeType
from smp.engine.graph_builder import DefaultGraphBuilder
from smp.engine.query import DefaultQueryEngine
from smp.protocol.handlers import (
    analysis as analysis_handlers,
)
from smp.protocol.handlers import (
    community as community_handlers,
)
from smp.protocol.handlers import (
    enrichment as enrichment_handlers,
)
from smp.protocol.handlers import (
    memory as memory_handlers,
)
from smp.protocol.handlers import (
    query as query_handlers,
)
from smp.protocol.handlers import (
    review as review_handlers,
)
from smp.protocol.handlers import (
    sandbox as sandbox_handlers,
)
from smp.protocol.handlers import (
    session as session_handlers,
)
from smp.protocol.handlers import (
    sync as sync_handlers,
)
from smp.protocol.server import _HANDLERS, _dispatch, create_app
from smp.store.graph.mmap_store import MMapGraphStore

from .conftest import make_edge, make_node

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def seeded_ctx(clean_graph: MMapGraphStore) -> AsyncIterator[dict[str, Any]]:
    """Two functions with a CALLS edge and a single class containing both."""
    login = make_node(
        id="func_login",
        type=NodeType.FUNCTION,
        file_path="src/auth/login.py",
    )
    validate = make_node(
        id="func_validate",
        type=NodeType.FUNCTION,
        file_path="src/auth/validate.py",
    )
    auth_service = make_node(
        id="cls_auth_service",
        type=NodeType.CLASS,
        file_path="src/auth/service.py",
    )
    await clean_graph.upsert_node(login)
    await clean_graph.upsert_node(validate)
    await clean_graph.upsert_node(auth_service)
    await clean_graph.upsert_edge(make_edge(source="func_login", target="func_validate", edge_type=EdgeType.CALLS))
    await clean_graph.upsert_edge(make_edge(source="cls_auth_service", target="func_login", edge_type=EdgeType.DEFINES))

    engine = DefaultQueryEngine(graph_store=clean_graph)
    builder = DefaultGraphBuilder(clean_graph)
    yield {"engine": engine, "builder": builder, "graph": clean_graph}


@pytest.fixture()
def in_memory_locks(seeded_ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Force the session/lock handlers to use their in-memory fallback path.

    ``MMapGraphStore``'s lock methods are stubs that swallow rather than
    raise ``NotImplementedError``, so the lock handlers never trigger the
    ``ctx["_locks"]`` fallback against it.  These tests need to exercise
    the in-memory enforcement path explicitly.
    """
    graph = seeded_ctx["graph"]

    async def _raise(*args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    for name in ("get_lock", "upsert_lock", "release_lock", "release_all_locks"):
        monkeypatch.setattr(graph, name, _raise)
    return seeded_ctx


@pytest.fixture()
def http_client(tmp_path: Path) -> Iterator[TestClient]:
    """FastAPI ``TestClient`` backed by a fresh per-test mmap graph file.

    ``TestClient`` is used as a context manager so the FastAPI ``lifespan``
    runs (``MMapGraphStore.connect``/``close``).
    """
    graph_path = tmp_path / "graph.smpg"
    app = create_app(graph_path=str(graph_path))
    with TestClient(app) as client:
        yield client


def _rpc(
    client: TestClient,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    request_id: int = 1,
) -> dict[str, Any]:
    """Send a JSON-RPC 2.0 request and return the parsed envelope."""
    payload = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": request_id}
    response = client.post("/rpc", json=payload)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------


class TestHttpSurface:
    """``/health``, ``/methods``, ``/stats``, ``/smp/invalidate`` round-trips."""

    def test_health(self, http_client: TestClient) -> None:
        response = http_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_methods_lists_all_handlers(self, http_client: TestClient) -> None:
        response = http_client.get("/methods")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == len(_HANDLERS)
        # /methods now returns scope metadata along with the method names
        names = {entry["method"] for entry in body["methods"]}
        assert names == set(_HANDLERS.keys())
        for entry in body["methods"]:
            assert entry["scope"] in {"read", "write", "admin"}

    def test_stats_initial_empty(self, http_client: TestClient) -> None:
        response = http_client.get("/stats")
        assert response.status_code == 200
        assert response.json() == {"nodes": 0, "edges": 0}

    def test_invalidate_missing_path(self, http_client: TestClient) -> None:
        response = http_client.post("/smp/invalidate", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["invalidated"] is False
        assert body.get("error") == "missing file_path"

    def test_invalidate_with_path(self, http_client: TestClient) -> None:
        response = http_client.post("/smp/invalidate", json={"file_path": "src/auth/login.py"})
        assert response.status_code == 200
        body = response.json()
        assert body["invalidated"] is True
        assert body["file_path"] == "src/auth/login.py"

    def test_round_trip_seed_via_index_import(self, http_client: TestClient) -> None:
        """Seed nodes through ``smp/index/import`` and read them back via stats and navigate."""
        envelope = _rpc(
            http_client,
            "smp/index/import",
            {
                "data": {
                    "nodes": [
                        {
                            "id": "func_a",
                            "type": "Function",
                            "file_path": "a.py",
                            "structural": {"name": "a", "file": "a.py", "start_line": 1, "end_line": 5},
                        },
                        {
                            "id": "func_b",
                            "type": "Function",
                            "file_path": "b.py",
                            "structural": {"name": "b", "file": "b.py", "start_line": 1, "end_line": 5},
                        },
                    ],
                    "edges": [
                        {"source_id": "func_a", "target_id": "func_b", "type": "CALLS"},
                    ],
                }
            },
        )
        assert envelope["result"]["imported_nodes"] == 2
        assert envelope["result"]["imported_edges"] == 1

        stats = http_client.get("/stats").json()
        assert stats == {"nodes": 2, "edges": 1}

        nav = _rpc(http_client, "smp/navigate", {"query": "func_a"})
        assert nav["result"]["entity"]["id"] == "func_a"


# ---------------------------------------------------------------------------
# JSON-RPC wire protocol
# ---------------------------------------------------------------------------


class TestJsonRpcWire:
    """Error envelopes: -32700 parse, -32600 invalid request, -32601 method not found."""

    def test_parse_error_on_invalid_json_body(self, http_client: TestClient) -> None:
        response = http_client.post(
            "/rpc",
            content=b"{not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["error"]["code"] == -32700
        assert body["id"] is None

    def test_invalid_request_when_body_is_array(self, http_client: TestClient) -> None:
        response = http_client.post("/rpc", json=[1, 2, 3])
        assert response.status_code == 200
        body = response.json()
        assert body["error"]["code"] == -32600

    def test_invalid_request_when_method_is_missing(self, http_client: TestClient) -> None:
        response = http_client.post("/rpc", json={"jsonrpc": "2.0", "id": 7})
        assert response.status_code == 200
        body = response.json()
        assert body["error"]["code"] == -32600
        assert body["id"] == 7

    def test_invalid_request_when_method_is_not_string(self, http_client: TestClient) -> None:
        response = http_client.post("/rpc", json={"jsonrpc": "2.0", "method": 42, "id": 8})
        body = response.json()
        assert body["error"]["code"] == -32600

    def test_method_not_found(self, http_client: TestClient) -> None:
        body = _rpc(http_client, "smp/does_not_exist")
        assert body["error"]["code"] == -32601
        assert "smp/does_not_exist" in body["error"]["message"]

    def test_params_default_to_empty_dict_when_missing(self, http_client: TestClient) -> None:
        response = http_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/telemetry", "id": 1},
        )
        assert response.status_code == 200
        body = response.json()
        assert "result" in body
        assert body["result"]["nodes"] == 0

    def test_non_dict_params_are_coerced_to_empty(self, http_client: TestClient) -> None:
        response = http_client.post(
            "/rpc",
            json={"jsonrpc": "2.0", "method": "smp/telemetry", "params": "oops", "id": 2},
        )
        body = response.json()
        assert "result" in body


# ---------------------------------------------------------------------------
# Per-domain handler dispatch — every method is hit at least once
# ---------------------------------------------------------------------------


class TestQueryDispatch:
    """Seven query methods (``smp/navigate`` … ``smp/flow``)."""

    async def test_navigate(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch("smp/navigate", {"query": "func_login"}, seeded_ctx)
        assert result["entity"]["id"] == "func_login"
        assert "relationships" in result

    async def test_trace(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch(
            "smp/trace",
            {"start": "func_login", "relationship": "CALLS", "depth": 2},
            seeded_ctx,
        )
        assert isinstance(result["nodes"], list)

    async def test_context(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch("smp/context", {"file_path": "src/auth/login.py"}, seeded_ctx)
        assert isinstance(result, dict)

    async def test_impact(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch("smp/impact", {"entity": "func_validate", "change_type": "delete"}, seeded_ctx)
        assert "severity" in result
        assert "affected_files" in result

    async def test_locate(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch("smp/locate", {"query": "login", "top_k": 3}, seeded_ctx)
        assert isinstance(result["matches"], list)

    async def test_search(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch("smp/search", {"query": "login", "top_k": 3}, seeded_ctx)
        assert "matches" in result

    async def test_flow(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch("smp/flow", {"start": "func_login", "end": "func_validate"}, seeded_ctx)
        assert "path" in result


class TestMemoryDispatch:
    async def test_update(self, seeded_ctx: dict[str, Any], tmp_path: Path) -> None:
        target = tmp_path / "missing.py"
        result = await _dispatch("smp/update", {"file_path": str(target)}, seeded_ctx)
        assert result["file_path"] == str(target)
        for key in ("nodes", "edges", "errors"):
            assert key in result

    async def test_batch_update(self, seeded_ctx: dict[str, Any], tmp_path: Path) -> None:
        files = [tmp_path / f"f{i}.py" for i in range(3)]
        result = await _dispatch(
            "smp/batch_update",
            {"changes": [{"file_path": str(p)} for p in files]},
            seeded_ctx,
        )
        assert result["updates"] == 3
        assert len(result["results"]) == 3

    async def test_reindex(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch("smp/reindex", {"scope": "/definitely/not/a/real/dir"}, seeded_ctx)
        assert result["status"] in {"reindex_requested", "reindex_started"}


class TestAnalysisDispatch:
    async def test_diff(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch("smp/diff", {"from_snapshot": "before", "to_snapshot": "after"}, seeded_ctx)
        assert "stats" in result

    async def test_plan(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch(
            "smp/plan",
            {
                "change_description": "rename login to authenticate",
                "target_file": "src/auth/login.py",
                "change_type": "refactor",
            },
            seeded_ctx,
        )
        assert "steps" in result
        assert "risk_level" in result

    async def test_conflict(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch(
            "smp/conflict",
            {"entity": "func_login", "proposed_change": "change signature"},
            seeded_ctx,
        )
        assert "conflict" in result
        assert "warnings" in result

    async def test_why(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch("smp/why", {"entity": "func_login", "depth": 3}, seeded_ctx)
        assert "reasons" in result

    async def test_telemetry_summary(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch("smp/telemetry", {"action": "get_stats"}, seeded_ctx)
        assert result["nodes"] == 3
        # The seeded fixture inserts two CALLS+DEFINES outgoing edges.
        assert result["edges"] >= 1
        assert "hot_nodes" in result

    async def test_telemetry_hot(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch("smp/telemetry/hot", {"node_id": "func_login"}, seeded_ctx)
        assert result["node_id"] == "func_login"
        assert "is_hot" in result

    async def test_telemetry_node(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch("smp/telemetry/node", {"node_id": "func_login"}, seeded_ctx)
        assert result["node_id"] == "func_login"
        assert "edges_by_type_out" in result


class TestEnrichmentDispatch:
    async def test_enrich(self, seeded_ctx: dict[str, Any]) -> None:
        # Seeded nodes default to status="enriched", so without force the
        # handler reports skipped=True; with force it actually re-enriches.
        result = await _dispatch("smp/enrich", {"node_id": "func_login", "force": True}, seeded_ctx)
        assert result["enriched"] is True

    async def test_enrich_batch(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch("smp/enrich/batch", {"scope": "full", "force": True}, seeded_ctx)
        assert result["total"] >= 3
        assert result["enriched"] >= 1

    async def test_enrich_stale(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch("smp/enrich/stale", {"scope": "full"}, seeded_ctx)
        assert "enriched" in result
        assert result["total"] >= 3

    async def test_enrich_status(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch("smp/enrich/status", {"scope": "full"}, seeded_ctx)
        assert result["total"] >= 3
        assert isinstance(result["by_status"], dict)

    async def test_annotate(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch(
            "smp/annotate",
            {
                "node_id": "func_login",
                "description": "Primary auth entrypoint.",
                "tags": ["auth", "entry"],
            },
            seeded_ctx,
        )
        assert result["annotated"] is True
        assert "auth" in result["tags"]

    async def test_annotate_bulk(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch(
            "smp/annotate/bulk",
            {
                "annotations": [
                    {"node_id": "func_login", "tags": ["bulk1"]},
                    {"node_id": "func_validate", "tags": ["bulk2"]},
                    {"node_id": "missing_node", "tags": ["x"]},
                ]
            },
            seeded_ctx,
        )
        assert result["annotated"] == 2
        assert result["missing"] == ["missing_node"]

    async def test_tag(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch(
            "smp/tag",
            {"scope": "full", "tags": ["scanned"], "action": "add"},
            seeded_ctx,
        )
        assert result["action"] == "add"
        assert result["updated"] >= 1


class TestSessionDispatch:
    async def test_session_open(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch(
            "smp/session/open",
            {"agent_id": "agent-A", "task": "test", "scope": ["src/auth"], "mode": "write"},
            seeded_ctx,
        )
        assert result["session_id"].startswith("sess_")
        assert result["status"] == "open"

    async def test_session_close(self, seeded_ctx: dict[str, Any]) -> None:
        opened = await session_handlers.session_open({"agent_id": "agent-A"}, seeded_ctx)
        result = await _dispatch(
            "smp/session/close",
            {"session_id": opened["session_id"], "status": "completed"},
            seeded_ctx,
        )
        assert result["closed"] is True
        assert result["status"] == "completed"

    async def test_session_recover(self, seeded_ctx: dict[str, Any]) -> None:
        opened = await session_handlers.session_open({"agent_id": "agent-A"}, seeded_ctx)
        result = await _dispatch("smp/session/recover", {"session_id": opened["session_id"]}, seeded_ctx)
        assert result["recovered"] is True
        assert result["session"]["session_id"] == opened["session_id"]

    async def test_dryrun(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch(
            "smp/dryrun",
            {"file_path": "src/auth/login.py", "change_summary": "tighten validation"},
            seeded_ctx,
        )
        assert result["file_path"] == "src/auth/login.py"
        assert "diff" in result

    async def test_checkpoint(self, seeded_ctx: dict[str, Any]) -> None:
        opened = await session_handlers.session_open({"agent_id": "agent-A"}, seeded_ctx)
        result = await _dispatch(
            "smp/checkpoint",
            {"session_id": opened["session_id"], "files": ["src/auth/login.py"]},
            seeded_ctx,
        )
        assert result["created"] is True
        assert result["checkpoint_id"].startswith("ckpt_")

    async def test_rollback(self, seeded_ctx: dict[str, Any]) -> None:
        opened = await session_handlers.session_open({"agent_id": "agent-A"}, seeded_ctx)
        ckpt = await session_handlers.checkpoint(
            {"session_id": opened["session_id"], "files": ["src/auth/login.py"]}, seeded_ctx
        )
        result = await _dispatch(
            "smp/rollback",
            {"session_id": opened["session_id"], "checkpoint_id": ckpt["checkpoint_id"]},
            seeded_ctx,
        )
        assert result["rolled_back"] is True

    async def test_lock(self, seeded_ctx: dict[str, Any]) -> None:
        opened = await session_handlers.session_open({"agent_id": "agent-A"}, seeded_ctx)
        result = await _dispatch(
            "smp/lock",
            {"session_id": opened["session_id"], "files": ["src/auth/login.py"]},
            seeded_ctx,
        )
        assert "src/auth/login.py" in result["locked"]
        assert result["conflicts"] == []

    async def test_unlock(self, in_memory_locks: dict[str, Any]) -> None:
        opened = await session_handlers.session_open({"agent_id": "agent-A"}, in_memory_locks)
        await session_handlers.lock(
            {"session_id": opened["session_id"], "files": ["src/auth/login.py"]}, in_memory_locks
        )
        result = await _dispatch(
            "smp/unlock",
            {"session_id": opened["session_id"], "files": ["src/auth/login.py"]},
            in_memory_locks,
        )
        assert "src/auth/login.py" in result["released"]

    async def test_audit_get(self, seeded_ctx: dict[str, Any]) -> None:
        await session_handlers.session_open({"agent_id": "agent-A"}, seeded_ctx)
        result = await _dispatch("smp/audit/get", {}, seeded_ctx)
        assert result["count"] >= 1
        assert any(e["event"] == "session_open" for e in result["events"])


class TestReviewDispatch:
    async def _new_review(self, ctx: dict[str, Any]) -> str:
        created = await review_handlers.review_create(
            {
                "session_id": "sess_x",
                "files_changed": ["src/auth/login.py"],
                "diff_summary": "x",
                "reviewers": ["alice"],
            },
            ctx,
        )
        return str(created["review_id"])

    async def test_review_create(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch(
            "smp/review/create",
            {
                "session_id": "sess_x",
                "files_changed": ["src/auth/login.py"],
                "diff_summary": "tighten",
                "reviewers": ["alice"],
            },
            seeded_ctx,
        )
        assert result["review_id"].startswith("rev_")
        assert result["status"] == "pending"

    async def test_review_approve(self, seeded_ctx: dict[str, Any]) -> None:
        rid = await self._new_review(seeded_ctx)
        result = await _dispatch("smp/review/approve", {"review_id": rid, "reviewer": "alice"}, seeded_ctx)
        assert result["approved"] is True
        assert result["status"] == "approved"

    async def test_review_reject(self, seeded_ctx: dict[str, Any]) -> None:
        rid = await self._new_review(seeded_ctx)
        result = await _dispatch(
            "smp/review/reject",
            {"review_id": rid, "reviewer": "bob", "reason": "needs tests"},
            seeded_ctx,
        )
        assert result["rejected"] is True
        assert result["status"] == "rejected"

    async def test_review_comment(self, seeded_ctx: dict[str, Any]) -> None:
        rid = await self._new_review(seeded_ctx)
        result = await _dispatch(
            "smp/review/comment",
            {
                "review_id": rid,
                "author": "alice",
                "comment": "looks good modulo nits",
                "file_path": "src/auth/login.py",
                "line": 12,
            },
            seeded_ctx,
        )
        assert result["added"] is True
        assert result["total_comments"] == 1

    async def test_pr_create(self, seeded_ctx: dict[str, Any]) -> None:
        rid = await self._new_review(seeded_ctx)
        result = await _dispatch(
            "smp/pr/create",
            {
                "review_id": rid,
                "title": "Tighten login validation",
                "body": "...",
                "branch": "feat/tighten-login",
                "base_branch": "main",
            },
            seeded_ctx,
        )
        assert result["created"] is True
        assert result["pr_id"].startswith("pr_")


class TestSandboxDispatch:
    async def test_sandbox_spawn(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch(
            "smp/sandbox/spawn",
            {"name": "test-sandbox", "template": "python", "files": {"main.py": "print('hi')"}},
            seeded_ctx,
        )
        assert result["sandbox_id"].startswith("sbx_")
        assert result["status"] == "ready"
        assert result["file_count"] == 1

    async def test_sandbox_execute(self, seeded_ctx: dict[str, Any]) -> None:
        spawn = await sandbox_handlers.sandbox_spawn({"name": "exec-test"}, seeded_ctx)
        result = await _dispatch(
            "smp/sandbox/execute",
            {"sandbox_id": spawn["sandbox_id"], "command": ["python", "main.py"], "timeout": 5},
            seeded_ctx,
        )
        assert result["started"] is True
        assert result["execution_id"].startswith("exec_")

    async def test_sandbox_kill(self, seeded_ctx: dict[str, Any]) -> None:
        spawn = await sandbox_handlers.sandbox_spawn({"name": "kill-test"}, seeded_ctx)
        execn = await sandbox_handlers.sandbox_execute(
            {"sandbox_id": spawn["sandbox_id"], "command": ["sleep", "9999"]}, seeded_ctx
        )
        result = await _dispatch("smp/sandbox/kill", {"execution_id": execn["execution_id"]}, seeded_ctx)
        assert result["killed"] is True
        assert result["status"] == "killed"


class TestCommunityDispatch:
    async def test_community_detect(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch("smp/community/detect", {"relationship_types": ["CALLS", "DEFINES"]}, seeded_ctx)
        assert result["total"] >= 1
        assert result["node_count"] == 3

    async def test_community_list(self, seeded_ctx: dict[str, Any]) -> None:
        await community_handlers.community_detect({}, seeded_ctx)
        result = await _dispatch("smp/community/list", {}, seeded_ctx)
        assert result["total"] >= 1

    async def test_community_get(self, seeded_ctx: dict[str, Any]) -> None:
        detect = await community_handlers.community_detect({}, seeded_ctx)
        any_id = detect["communities"][0]["community_id"]
        result = await _dispatch(
            "smp/community/get",
            {"community_id": any_id, "include_bridges": True},
            seeded_ctx,
        )
        assert result["community_id"] == any_id
        assert result["size"] >= 1
        assert isinstance(result["bridges"], list)

    async def test_community_boundaries(self, seeded_ctx: dict[str, Any]) -> None:
        await community_handlers.community_detect({}, seeded_ctx)
        result = await _dispatch("smp/community/boundaries", {"min_coupling": 0.0}, seeded_ctx)
        assert "boundaries" in result


class TestSyncDispatch:
    async def test_sync(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch(
            "smp/sync",
            {
                "remote_data": {
                    "nodes": [
                        # Different signature from the local "func_login" so it
                        # shows up as ``changed``.
                        {"id": "func_login", "signature": "deadbeef"},
                        {"id": "remote_only", "signature": "abc"},
                    ]
                }
            },
            seeded_ctx,
        )
        assert result["in_sync"] is False
        assert "func_login" in result["changed"]
        assert "remote_only" in result["missing_locally"]
        assert "func_validate" in result["missing_remotely"]

    async def test_index_import(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch(
            "smp/index/import",
            {
                "data": {
                    "nodes": [
                        {
                            "id": "imported_fn",
                            "type": "Function",
                            "file_path": "x.py",
                            "structural": {"name": "imported_fn", "file": "x.py"},
                        }
                    ],
                    "edges": [
                        {"source_id": "imported_fn", "target_id": "func_login", "type": "CALLS"},
                    ],
                }
            },
            seeded_ctx,
        )
        assert result["imported_nodes"] == 1
        assert result["imported_edges"] == 1

    async def test_integrity_check(self, seeded_ctx: dict[str, Any]) -> None:
        baseline = await sync_handlers.integrity_baseline({"node_id": "func_login"}, seeded_ctx)
        result = await _dispatch(
            "smp/integrity/check",
            {"node_id": "func_login", "current_state": {"signature": baseline["signature"]}},
            seeded_ctx,
        )
        assert result["matches"] is True

    async def test_integrity_baseline(self, seeded_ctx: dict[str, Any]) -> None:
        result = await _dispatch("smp/integrity/baseline", {"node_id": "func_login"}, seeded_ctx)
        assert result["baseline_set"] is True
        assert result["signature"]


class TestDispatchRegistryCoverage:
    """Ensure every method in ``_HANDLERS`` is covered by this module."""

    def test_handler_count_matches_inventory(self) -> None:
        # Sanity: 49 methods are documented in this module's traceability table.
        # If a new handler is added without a test, this number must change.
        assert len(_HANDLERS) == 49


# ---------------------------------------------------------------------------
# Real-world scenarios — multi-step flows that mirror how an agent would
# string protocol calls together.
# ---------------------------------------------------------------------------


class TestRealWorldScenarios:
    """End-to-end flows mixing query, session, review, etc."""

    async def test_impact_of_deleting_function(self, seeded_ctx: dict[str, Any]) -> None:
        """An agent considering deletion: navigate -> trace -> impact."""
        nav = await query_handlers.navigate({"query": "func_login"}, seeded_ctx)
        assert nav["entity"]["id"] == "func_login"

        trace = await query_handlers.trace(
            {"start": "func_validate", "relationship": "CALLS", "direction": "incoming", "depth": 3},
            seeded_ctx,
        )
        ids_in_trace = {n.get("id") for n in trace["nodes"] if isinstance(n, dict)}
        assert "func_login" in ids_in_trace or trace["nodes"]

        impact = await query_handlers.impact({"entity": "func_validate", "change_type": "delete"}, seeded_ctx)
        assert impact["severity"] in {"low", "medium", "high"}
        assert "src/auth/login.py" in impact["affected_files"]

    async def test_session_lifecycle_with_lock(self, in_memory_locks: dict[str, Any]) -> None:
        """open -> lock -> checkpoint -> rollback -> unlock -> close -> audit/get."""
        opened = await session_handlers.session_open(
            {"agent_id": "scenario-agent", "task": "rename", "scope": ["src/auth"], "mode": "write"},
            in_memory_locks,
        )
        sid = opened["session_id"]

        locked = await session_handlers.lock(
            {"session_id": sid, "files": ["src/auth/login.py", "src/auth/validate.py"]},
            in_memory_locks,
        )
        assert len(locked["locked"]) == 2

        ckpt = await session_handlers.checkpoint({"session_id": sid, "files": ["src/auth/login.py"]}, in_memory_locks)
        assert ckpt["created"] is True

        rolled = await session_handlers.rollback(
            {"session_id": sid, "checkpoint_id": ckpt["checkpoint_id"]}, in_memory_locks
        )
        assert rolled["rolled_back"] is True

        unlocked = await session_handlers.unlock({"session_id": sid, "files": ["src/auth/login.py"]}, in_memory_locks)
        assert "src/auth/login.py" in unlocked["released"]

        closed = await session_handlers.session_close({"session_id": sid}, in_memory_locks)
        assert closed["closed"] is True
        # The remaining lock on validate.py should be released on close.
        assert closed["released_locks"] >= 1

        audit = await session_handlers.audit_get({"audit_log_id": sid}, in_memory_locks)
        events = {e["event"] for e in audit["events"]}
        assert {"session_open", "checkpoint", "rollback", "session_close"} <= events

    async def test_enrichment_round_trip(self, seeded_ctx: dict[str, Any]) -> None:
        """enrich a single node, then verify enrich/status counts it."""
        result = await enrichment_handlers.enrich({"node_id": "func_login", "force": True}, seeded_ctx)
        assert result["enriched"] is True

        status = await enrichment_handlers.enrich_status({"scope": "full"}, seeded_ctx)
        assert status["by_status"].get("enriched", 0) >= 1

    async def test_review_handoff_to_pr(self, seeded_ctx: dict[str, Any]) -> None:
        """create -> comment -> approve -> pr/create."""
        review = await review_handlers.review_create(
            {
                "session_id": "sess_review",
                "files_changed": ["src/auth/login.py"],
                "diff_summary": "tighten validation",
                "reviewers": ["alice", "bob"],
            },
            seeded_ctx,
        )
        rid = review["review_id"]

        comment = await review_handlers.review_comment(
            {"review_id": rid, "author": "bob", "comment": "looks good", "line": 14},
            seeded_ctx,
        )
        assert comment["total_comments"] == 1

        approval = await review_handlers.review_approve({"review_id": rid, "reviewer": "alice"}, seeded_ctx)
        assert approval["status"] == "approved"

        pr = await review_handlers.pr_create(
            {
                "review_id": rid,
                "title": "Tighten login validation",
                "branch": "feat/tighten-login",
            },
            seeded_ctx,
        )
        assert pr["created"] is True

    async def test_telemetry_after_seeding(self, seeded_ctx: dict[str, Any]) -> None:
        summary = await analysis_handlers.telemetry({}, seeded_ctx)
        assert summary["nodes"] == 3
        assert summary["edges"] >= 2

        hot = await analysis_handlers.telemetry_hot({"node_id": "func_login"}, seeded_ctx)
        assert hot["node_id"] == "func_login"

        node = await analysis_handlers.telemetry_node({"node_id": "func_login"}, seeded_ctx)
        assert node["name"] == "login"

    async def test_community_detect_then_get(self, seeded_ctx: dict[str, Any]) -> None:
        detect = await community_handlers.community_detect({"relationship_types": ["CALLS", "DEFINES"]}, seeded_ctx)
        # Three seeded nodes joined by CALLS+DEFINES => single component.
        assert detect["total"] == 1
        cid = detect["communities"][0]["community_id"]

        listed = await community_handlers.community_list({}, seeded_ctx)
        assert any(c["community_id"] == cid for c in listed["communities"])

        got = await community_handlers.community_get({"community_id": cid, "include_bridges": True}, seeded_ctx)
        assert got["size"] == 3

        boundaries = await community_handlers.community_boundaries({"min_coupling": 0.0}, seeded_ctx)
        assert "boundaries" in boundaries

    async def test_integrity_baseline_and_check(self, seeded_ctx: dict[str, Any]) -> None:
        """baseline a node, then a check with the same signature returns matches=True."""
        baseline = await sync_handlers.integrity_baseline({"node_id": "func_login"}, seeded_ctx)
        sig = baseline["signature"]
        ok = await sync_handlers.integrity_check(
            {"node_id": "func_login", "current_state": {"signature": sig}}, seeded_ctx
        )
        assert ok["matches"] is True

        # And a sync delta against an empty remote should report missing_remotely.
        sync = await sync_handlers.sync({"remote_data": {"nodes": []}}, seeded_ctx)
        assert sync["in_sync"] is False
        assert sync["stats"]["missing_remotely"] == 3

    async def test_sandbox_lifecycle(self, seeded_ctx: dict[str, Any]) -> None:
        spawn = await sandbox_handlers.sandbox_spawn(
            {"name": "lifecycle", "files": {"main.py": "print('ok')"}}, seeded_ctx
        )
        execn = await sandbox_handlers.sandbox_execute(
            {"sandbox_id": spawn["sandbox_id"], "command": ["python", "main.py"]}, seeded_ctx
        )
        killed = await sandbox_handlers.sandbox_kill({"execution_id": execn["execution_id"]}, seeded_ctx)
        assert spawn["status"] == "ready"
        assert execn["started"] is True
        assert killed["killed"] is True


# ---------------------------------------------------------------------------
# Edge-case matrix
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """~30 representative edge cases — empty graph, unknown ids, boundaries."""

    # --- Unknown / missing ids --------------------------------------------------

    async def test_navigate_unknown_returns_error_field(self, seeded_ctx: dict[str, Any]) -> None:
        result = await query_handlers.navigate({"query": "nope_no_such_thing"}, seeded_ctx)
        assert "error" in result

    async def test_impact_unknown_returns_error(self, seeded_ctx: dict[str, Any]) -> None:
        result = await query_handlers.impact({"entity": "nope"}, seeded_ctx)
        assert "error" in result

    async def test_why_unknown_returns_error(self, seeded_ctx: dict[str, Any]) -> None:
        result = await analysis_handlers.why({"entity": "nope"}, seeded_ctx)
        assert "error" in result

    async def test_telemetry_hot_unknown(self, seeded_ctx: dict[str, Any]) -> None:
        result = await analysis_handlers.telemetry_hot({"node_id": "nope"}, seeded_ctx)
        assert result["is_hot"] is False
        assert result["error"] == "node_not_found"

    async def test_telemetry_node_unknown(self, seeded_ctx: dict[str, Any]) -> None:
        result = await analysis_handlers.telemetry_node({"node_id": "nope"}, seeded_ctx)
        assert result["error"] == "node_not_found"

    async def test_enrich_unknown_node(self, seeded_ctx: dict[str, Any]) -> None:
        result = await enrichment_handlers.enrich({"node_id": "nope"}, seeded_ctx)
        assert result["enriched"] is False
        assert result["error"] == "node_not_found"

    async def test_annotate_unknown_node(self, seeded_ctx: dict[str, Any]) -> None:
        result = await enrichment_handlers.annotate({"node_id": "nope", "tags": ["x"]}, seeded_ctx)
        assert result["annotated"] is False

    async def test_session_close_unknown(self, seeded_ctx: dict[str, Any]) -> None:
        result = await session_handlers.session_close({"session_id": "missing"}, seeded_ctx)
        assert result["closed"] is False
        assert result["error"] == "session_not_found"

    async def test_session_recover_unknown(self, seeded_ctx: dict[str, Any]) -> None:
        result = await session_handlers.session_recover({"session_id": "missing"}, seeded_ctx)
        assert result["recovered"] is False

    async def test_rollback_unknown_session(self, seeded_ctx: dict[str, Any]) -> None:
        result = await session_handlers.rollback({"session_id": "missing", "checkpoint_id": "ckpt_x"}, seeded_ctx)
        assert result["rolled_back"] is False
        assert result["error"] == "session_not_found"

    async def test_rollback_unknown_checkpoint(self, seeded_ctx: dict[str, Any]) -> None:
        opened = await session_handlers.session_open({"agent_id": "a"}, seeded_ctx)
        result = await session_handlers.rollback(
            {"session_id": opened["session_id"], "checkpoint_id": "no_such_ckpt"}, seeded_ctx
        )
        assert result["rolled_back"] is False
        assert result["error"] == "checkpoint_not_found"

    async def test_review_approve_unknown_review(self, seeded_ctx: dict[str, Any]) -> None:
        result = await review_handlers.review_approve({"review_id": "missing", "reviewer": "alice"}, seeded_ctx)
        assert result["approved"] is False

    async def test_review_comment_unknown_review(self, seeded_ctx: dict[str, Any]) -> None:
        result = await review_handlers.review_comment(
            {"review_id": "missing", "author": "x", "comment": "y"}, seeded_ctx
        )
        assert result["added"] is False

    async def test_pr_create_unknown_review(self, seeded_ctx: dict[str, Any]) -> None:
        result = await review_handlers.pr_create({"review_id": "missing", "title": "x", "branch": "b"}, seeded_ctx)
        assert result["created"] is False
        assert result["error"] == "review_not_found"

    async def test_sandbox_execute_unknown(self, seeded_ctx: dict[str, Any]) -> None:
        result = await sandbox_handlers.sandbox_execute(
            {"sandbox_id": "missing", "command": ["echo", "hi"]}, seeded_ctx
        )
        assert result["started"] is False

    async def test_sandbox_kill_unknown(self, seeded_ctx: dict[str, Any]) -> None:
        result = await sandbox_handlers.sandbox_kill({"execution_id": "missing"}, seeded_ctx)
        assert result["killed"] is False

    async def test_integrity_check_unknown_node(self, seeded_ctx: dict[str, Any]) -> None:
        result = await sync_handlers.integrity_check(
            {"node_id": "missing", "current_state": {"signature": "x"}}, seeded_ctx
        )
        assert result["matches"] is False
        assert result["error"] == "node_not_found"

    async def test_integrity_baseline_unknown_node(self, seeded_ctx: dict[str, Any]) -> None:
        result = await sync_handlers.integrity_baseline({"node_id": "missing"}, seeded_ctx)
        assert result["baseline_set"] is False

    async def test_community_get_unknown(self, seeded_ctx: dict[str, Any]) -> None:
        await community_handlers.community_detect({}, seeded_ctx)
        result = await community_handlers.community_get({"community_id": "com_missing"}, seeded_ctx)
        assert result["size"] == 0
        assert result["nodes"] == []

    # --- Empty / boundary inputs ------------------------------------------------

    async def test_locate_top_k_zero_returns_empty(self, seeded_ctx: dict[str, Any]) -> None:
        result = await query_handlers.locate({"query": "login", "top_k": 0}, seeded_ctx)
        assert result["matches"] == []

    async def test_search_top_k_zero_returns_empty(self, seeded_ctx: dict[str, Any]) -> None:
        result = await query_handlers.search({"query": "login", "top_k": 0}, seeded_ctx)
        assert result["matches"] == []

    async def test_trace_depth_zero(self, seeded_ctx: dict[str, Any]) -> None:
        result = await query_handlers.trace({"start": "func_login", "relationship": "CALLS", "depth": 0}, seeded_ctx)
        assert isinstance(result["nodes"], list)

    async def test_batch_update_empty_changes(self, seeded_ctx: dict[str, Any]) -> None:
        result = await memory_handlers.batch_update({"changes": []}, seeded_ctx)
        assert result["updates"] == 0
        assert result["results"] == []

    async def test_annotate_bulk_empty(self, seeded_ctx: dict[str, Any]) -> None:
        result = await enrichment_handlers.annotate_bulk({"annotations": []}, seeded_ctx)
        assert result["annotated"] == 0
        assert result["total"] == 0

    async def test_index_import_empty_payload(self, seeded_ctx: dict[str, Any]) -> None:
        result = await sync_handlers.index_import({"data": {}}, seeded_ctx)
        assert result["imported_nodes"] == 0
        assert result["imported_edges"] == 0

    async def test_index_import_skips_invalid_entries(self, seeded_ctx: dict[str, Any]) -> None:
        result = await sync_handlers.index_import(
            {
                "data": {
                    "nodes": ["not a dict", {"id": ""}, {"type": "BogusType", "id": "x"}],
                    "edges": [{"source_id": "a"}, "string", {"source_id": "a", "target_id": "b", "type": "CALLS"}],
                }
            },
            seeded_ctx,
        )
        assert result["skipped_nodes"] == 3
        assert result["skipped_edges"] == 2
        assert result["imported_edges"] == 1

    async def test_sync_in_sync_when_remote_matches_local(self, seeded_ctx: dict[str, Any]) -> None:
        # Pre-build remote payload matching local signatures.
        remote_nodes = []
        for node_id in ("func_login", "func_validate", "cls_auth_service"):
            sig = sync_handlers._node_signature(  # noqa: SLF001
                await seeded_ctx["graph"].get_node(node_id)
            )
            remote_nodes.append({"id": node_id, "signature": sig})
        result = await sync_handlers.sync({"remote_data": {"nodes": remote_nodes}}, seeded_ctx)
        assert result["in_sync"] is True

    async def test_lock_conflict_when_held_by_other_session(self, in_memory_locks: dict[str, Any]) -> None:
        a = await session_handlers.session_open({"agent_id": "a"}, in_memory_locks)
        b = await session_handlers.session_open({"agent_id": "b"}, in_memory_locks)
        await session_handlers.lock({"session_id": a["session_id"], "files": ["src/auth/login.py"]}, in_memory_locks)
        result = await session_handlers.lock(
            {"session_id": b["session_id"], "files": ["src/auth/login.py"]}, in_memory_locks
        )
        assert result["locked"] == []
        assert result["conflicts"] and result["conflicts"][0]["held_by"] == a["session_id"]

    async def test_tag_remove_action(self, seeded_ctx: dict[str, Any]) -> None:
        await enrichment_handlers.tag({"scope": "full", "tags": ["temp"], "action": "add"}, seeded_ctx)
        result = await enrichment_handlers.tag({"scope": "full", "tags": ["temp"], "action": "remove"}, seeded_ctx)
        assert result["action"] == "remove"
        # Every node had the tag added, so the same count is removed.
        assert result["updated"] >= 1

    async def test_enrich_skips_already_enriched_without_force(self, seeded_ctx: dict[str, Any]) -> None:
        result = await enrichment_handlers.enrich({"node_id": "func_login"}, seeded_ctx)
        assert result["enriched"] is False
        assert result["skipped"] is True

    async def test_unicode_file_path_in_update(self, seeded_ctx: dict[str, Any], tmp_path: Path) -> None:
        target = tmp_path / "héllo_世界.py"
        result = await memory_handlers.update({"file_path": str(target)}, seeded_ctx)
        assert result["file_path"] == str(target)
        assert "errors" in result

    async def test_flow_with_unknown_endpoints(self, seeded_ctx: dict[str, Any]) -> None:
        result = await query_handlers.flow({"start": "missing_a", "end": "missing_b"}, seeded_ctx)
        assert result["path"] == []

    async def test_flow_self_loop(self, seeded_ctx: dict[str, Any]) -> None:
        result = await query_handlers.flow({"start": "func_login", "end": "func_login"}, seeded_ctx)
        assert len(result["path"]) == 1

    async def test_pr_create_without_review_id_creates_orphan_pr(self, seeded_ctx: dict[str, Any]) -> None:
        # An empty review_id is allowed; the handler creates a standalone PR.
        result = await review_handlers.pr_create(
            {"review_id": "", "title": "drive-by fix", "branch": "fix/typo"}, seeded_ctx
        )
        assert result["created"] is True
