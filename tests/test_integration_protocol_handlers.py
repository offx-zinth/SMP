"""Integration tests for SMP protocol handlers.

The legacy ``RpcDispatcher`` and per-domain handler classes have been replaced
by plain async functions in :mod:`smp.protocol.handlers.query` and
:mod:`smp.protocol.handlers.memory`, dispatched inline from
:mod:`smp.protocol.server`.  These tests exercise both layers end-to-end
against a real ``MMapGraphStore``.
"""

from __future__ import annotations

import pytest

from smp.core.models import EdgeType, NodeType
from smp.engine.graph_builder import DefaultGraphBuilder
from smp.engine.query import DefaultQueryEngine
from smp.protocol.handlers import memory as memory_handlers
from smp.protocol.handlers import query as query_handlers
from smp.protocol.server import _MethodNotFoundError, _dispatch
from smp.store.graph.mmap_store import MMapGraphStore

from .conftest import make_edge, make_node


@pytest.fixture()
async def seeded_ctx(clean_graph: MMapGraphStore) -> dict[str, object]:
    """A small graph + dispatch context wired around it."""
    login = make_node(id="func_login", file_path="src/auth/login.py")
    validate = make_node(
        id="func_validate",
        type=NodeType.FUNCTION,
        file_path="src/auth/validate.py",
    )
    await clean_graph.upsert_node(login)
    await clean_graph.upsert_node(validate)
    await clean_graph.upsert_edge(
        make_edge(source="func_login", target="func_validate", edge_type=EdgeType.CALLS)
    )

    engine = DefaultQueryEngine(graph_store=clean_graph)
    builder = DefaultGraphBuilder(clean_graph)
    return {"engine": engine, "builder": builder, "graph": clean_graph}


# ---------------------------------------------------------------------------
# Query handlers — direct function calls
# ---------------------------------------------------------------------------


class TestQueryHandlers:
    """The ``smp/navigate`` … ``smp/flow`` handler functions."""

    async def test_navigate_returns_entity(self, seeded_ctx: dict[str, object]) -> None:
        result = await query_handlers.navigate(
            {"query": "func_login", "include_relationships": True}, seeded_ctx
        )
        assert isinstance(result, dict)
        assert "entity" in result

    async def test_trace_returns_node_list(self, seeded_ctx: dict[str, object]) -> None:
        result = await query_handlers.trace(
            {"start": "func_login", "relationship": "CALLS", "depth": 2}, seeded_ctx
        )
        assert isinstance(result, dict)
        assert "nodes" in result
        assert isinstance(result["nodes"], list)

    async def test_context_returns_dict(self, seeded_ctx: dict[str, object]) -> None:
        result = await query_handlers.context({"file_path": "src/auth/login.py"}, seeded_ctx)
        assert isinstance(result, dict)

    async def test_impact_returns_dict(self, seeded_ctx: dict[str, object]) -> None:
        result = await query_handlers.impact(
            {"entity": "func_login", "change_type": "delete"}, seeded_ctx
        )
        assert isinstance(result, dict)

    async def test_locate_returns_matches(self, seeded_ctx: dict[str, object]) -> None:
        result = await query_handlers.locate({"query": "login", "top_k": 3}, seeded_ctx)
        assert isinstance(result, dict)
        assert "matches" in result

    async def test_search_returns_dict(self, seeded_ctx: dict[str, object]) -> None:
        result = await query_handlers.search({"query": "login", "top_k": 3}, seeded_ctx)
        assert isinstance(result, dict)

    async def test_flow_returns_dict(self, seeded_ctx: dict[str, object]) -> None:
        result = await query_handlers.flow(
            {"start": "func_login", "end": "func_validate"}, seeded_ctx
        )
        assert isinstance(result, dict)
        assert "path" in result


# ---------------------------------------------------------------------------
# Memory handlers
# ---------------------------------------------------------------------------


class TestMemoryHandlers:
    """The ``smp/update``, ``smp/batch_update``, ``smp/reindex`` handlers."""

    async def test_update_returns_status_envelope(
        self, seeded_ctx: dict[str, object], tmp_path
    ) -> None:
        # Use a path that does not exist; update should still produce a
        # well-formed envelope, since MMapGraphStore tolerates unknown files.
        target = tmp_path / "missing.py"
        result = await memory_handlers.update({"file_path": str(target)}, seeded_ctx)
        assert isinstance(result, dict)
        assert result["file_path"] == str(target)
        for key in ("nodes", "edges", "errors"):
            assert key in result

    async def test_batch_update_aggregates_results(
        self, seeded_ctx: dict[str, object], tmp_path
    ) -> None:
        files = [tmp_path / f"f{i}.py" for i in range(3)]
        result = await memory_handlers.batch_update(
            {"changes": [{"file_path": str(p)} for p in files]}, seeded_ctx
        )
        assert result["updates"] == 3
        assert len(result["results"]) == 3

    async def test_reindex_returns_status(self, seeded_ctx: dict[str, object]) -> None:
        # Pass a non-directory scope; the handler should still acknowledge the request.
        result = await memory_handlers.reindex({"scope": "/definitely/not/a/real/dir"}, seeded_ctx)
        assert isinstance(result, dict)
        assert "status" in result


# ---------------------------------------------------------------------------
# Inline server dispatch
# ---------------------------------------------------------------------------


class TestServerDispatch:
    """Round-trip through :func:`smp.protocol.server._dispatch`."""

    async def test_dispatch_navigate(self, seeded_ctx: dict[str, object]) -> None:
        result = await _dispatch("smp/navigate", {"query": "func_login"}, seeded_ctx)
        assert "entity" in result

    async def test_dispatch_trace(self, seeded_ctx: dict[str, object]) -> None:
        result = await _dispatch(
            "smp/trace",
            {"start": "func_login", "relationship": "CALLS", "depth": 2},
            seeded_ctx,
        )
        assert "nodes" in result

    async def test_dispatch_unknown_method_raises(self, seeded_ctx: dict[str, object]) -> None:
        with pytest.raises(_MethodNotFoundError) as excinfo:
            await _dispatch("smp/does_not_exist", {}, seeded_ctx)
        assert excinfo.value.method == "smp/does_not_exist"

    @pytest.mark.parametrize(
        "method",
        [
            "smp/navigate",
            "smp/trace",
            "smp/context",
            "smp/impact",
            "smp/locate",
            "smp/search",
            "smp/flow",
            "smp/update",
            "smp/batch_update",
            "smp/reindex",
        ],
    )
    async def test_known_methods_are_dispatched(
        self, seeded_ctx: dict[str, object], method: str
    ) -> None:
        # We don't assert the exact shape — only that the method is recognised
        # (i.e. ``_MethodNotFoundError`` is *not* raised).
        try:
            await _dispatch(method, {"query": "x", "file_path": "x", "scope": "full"}, seeded_ctx)
        except _MethodNotFoundError:
            pytest.fail(f"method {method!r} should be registered")
        except Exception:  # noqa: BLE001
            # Handler may legitimately raise on the synthetic params; that's
            # outside the scope of this dispatch-routing check.
            pass
