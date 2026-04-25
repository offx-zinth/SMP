"""Shared test fixtures for SMP tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from smp.core.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    SemanticProperties,
    StructuralProperties,
)
from smp.store.graph.mmap_store import MMapGraphStore

# ---------------------------------------------------------------------------
# Memory-mapped graph store fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def graph_store(tmp_path: Path) -> AsyncIterator[MMapGraphStore]:
    """Provide a connected ``MMapGraphStore`` backed by a per-test mmap file.

    A fresh ``.smpg`` file is created under ``tmp_path`` for each test.  The
    store is closed automatically when the test finishes.
    """
    graph_path = tmp_path / "graph.smpg"
    store = MMapGraphStore(path=graph_path)
    await store.connect()
    try:
        yield store
    finally:
        await store.close()


@pytest.fixture()
async def clean_graph(graph_store: MMapGraphStore) -> AsyncIterator[MMapGraphStore]:
    """Backwards-compatible alias for :func:`graph_store`.

    ``MMapGraphStore`` already starts empty per-test, so no extra cleanup is
    required.  The fixture is kept so existing tests that reference
    ``clean_graph`` continue to work.
    """
    yield graph_store


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------


def make_node(
    id: str = "func_login",
    type: NodeType = NodeType.FUNCTION,
    file_path: str = "src/auth/login.py",
    structural: StructuralProperties | None = None,
    semantic: SemanticProperties | None = None,
) -> GraphNode:
    if structural is None:
        structural = StructuralProperties(
            name="login",
            file=file_path,
            signature="def login(user: User) -> Token:",
            start_line=10,
            end_line=25,
            lines=16,
        )
    if semantic is None:
        semantic = SemanticProperties(
            docstring="Authenticate user and return token.",
            status="enriched",
        )
    return GraphNode(
        id=id,
        type=type,
        file_path=file_path,
        structural=structural,
        semantic=semantic,
    )


def make_edge(
    source: str = "func_login",
    target: str = "func_validate",
    edge_type: EdgeType = EdgeType.CALLS,
) -> GraphEdge:
    return GraphEdge(source_id=source, target_id=target, type=edge_type)
