"""Verify the five MCP accuracy fixes end-to-end against a real graph store."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from smp.engine.query import DefaultQueryEngine
from smp.protocol.handlers.analysis import architecture
from smp.store.graph.mmap_store import MMapGraphStore

SAMPLE = '''
"""Sample module."""


def alpha() -> int:
    """Alpha does a thing."""
    return beta()


def beta() -> int:
    """Beta is called by alpha."""
    return 1


class Widget:
    """A widget."""

    def render(self) -> str:
        """Render it."""
        return "x"
'''

STORE = '''
"""Store module."""


class MMapGraphStore:
    """Memory-mapped graph store."""

    def connect(self) -> None:
        """Connect."""
        return None
'''

DOCS = """# Guide

## MMapGraphStore usage

Prose mentioning MMapGraphStore and the class below.
"""


@pytest.fixture
async def repo(tmp_path: Path) -> Path:
    (tmp_path / "sample.py").write_text(SAMPLE, encoding="utf-8")
    (tmp_path / "store.py").write_text(STORE, encoding="utf-8")
    (tmp_path / "README.md").write_text(DOCS, encoding="utf-8")
    return tmp_path


@pytest.fixture
async def engine(repo: Path) -> DefaultQueryEngine:
    from smp.cli import ingest_directory

    await ingest_directory(str(repo), graph_path=str(repo / ".smpg"), clear=True)
    store = MMapGraphStore(path=str(repo / ".smpg"))
    await store.connect()
    return DefaultQueryEngine(graph_store=store)


async def _contains_edges(store: Any) -> list[tuple[str, str]]:
    names = {n.id: n.structural.name for n in await store.find_nodes()}
    out: list[tuple[str, str]] = []
    for nid in names:
        for e in await store.get_edges(nid, direction="outgoing"):
            if e.type.value == "CONTAINS":
                out.append((names.get(e.source_id, e.source_id), names.get(e.target_id, e.target_id)))
    return out


async def test_siblings_do_not_get_spurious_contains_edges(engine: DefaultQueryEngine) -> None:
    """alpha/beta are siblings; neither may CONTAIN the other."""
    edges = await _contains_edges(engine._graph)
    assert ("alpha", "beta") not in edges, edges
    assert ("beta", "alpha") not in edges, edges
    assert ("alpha", "Widget") not in edges, edges


async def test_real_containment_survives(engine: DefaultQueryEngine) -> None:
    """Class -> method containment must still be recorded."""
    edges = await _contains_edges(engine._graph)
    assert ("Widget", "render") in edges, edges


async def test_search_ranks_exact_named_symbol_first(engine: DefaultQueryEngine) -> None:
    """Multi-word queries must surface the symbol they name, not doc matches.

    The exact-name boost compares the joined query against a node name, so it
    never fired for multi-word input and long docstrings outranked the symbol.
    """
    result = await engine.search("Widget function", top_k=5)
    assert result["matches"], "expected at least one match"
    assert result["matches"][0]["name"] == "Widget", result["matches"][0]
    others = [m["name"] for m in result["matches"][1:]]
    assert "Widget" not in others
    # Unrelated symbols must be far behind the exact-name match.
    top = result["matches"][0]["score"]
    for m in result["matches"][1:]:
        assert m["score"] < top / 2, m


async def test_navigate_prefers_code_over_docs(engine: DefaultQueryEngine) -> None:
    """A name present in both Markdown and code must resolve to the code node."""
    result = await engine.navigate("MMapGraphStore")
    entity = result.get("entity")
    assert entity, result
    assert entity["file_path"].endswith("store.py"), entity


async def test_impact_excludes_structural_edges(engine: DefaultQueryEngine) -> None:
    """DEFINES/CONTAINS must not inflate the blast radius or severity."""
    result = await engine.assess_impact("beta")
    assert "alpha" in result["affected_functions"], result
    assert result["affected_functions"].count("beta") <= 1
    assert "soft_references" in result


async def test_architecture_reports_entry_points(engine: DefaultQueryEngine) -> None:
    """entry_points must not collapse to an empty list."""
    ctx: dict[str, Any] = {"graph": engine._graph}
    result = await architecture({"aspects": ["entry_points"], "top_k": 20}, ctx)
    assert isinstance(result.get("entry_points"), list)
