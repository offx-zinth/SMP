"""Tests for the static semantic enricher — SMP(3)."""

from __future__ import annotations

import pytest

from smp.core.models import (
    Annotations,
    GraphNode,
    NodeType,
    SemanticProperties,
    StructuralProperties,
)
from smp.engine.enricher import StaticSemanticEnricher, _compute_source_hash

# ---------------------------------------------------------------------------
# Source hash
# ---------------------------------------------------------------------------


class TestSourceHash:
    def test_deterministic(self) -> None:
        h1 = _compute_source_hash("foo", "test.py", 1, 5, "def foo():")
        h2 = _compute_source_hash("foo", "test.py", 1, 5, "def foo():")
        assert h1 == h2

    def test_different_names_differ(self) -> None:
        h1 = _compute_source_hash("foo", "test.py", 1, 5, "def foo():")
        h2 = _compute_source_hash("bar", "test.py", 1, 5, "def bar():")
        assert h1 != h2

    def test_different_files_differ(self) -> None:
        h1 = _compute_source_hash("foo", "a.py", 1, 5, "def foo():")
        h2 = _compute_source_hash("foo", "b.py", 1, 5, "def foo():")
        assert h1 != h2


# ---------------------------------------------------------------------------
# Enricher (static mode, no API key)
# ---------------------------------------------------------------------------


class TestStaticSemanticEnricher:
    @pytest.fixture()
    def enricher(self) -> StaticSemanticEnricher:
        return StaticSemanticEnricher()

    def _make_node(
        self,
        id: str = "test::Function::foo::1",
        name: str = "foo",
        docstring: str = "",
        decorators: list[str] | None = None,
        annotations: Annotations | None = None,
    ) -> GraphNode:
        return GraphNode(
            id=id,
            type=NodeType.FUNCTION,
            file_path="test.py",
            structural=StructuralProperties(
                name=name,
                file="test.py",
                signature=f"def {name}():",
                start_line=1,
                end_line=5,
                lines=5,
            ),
            semantic=SemanticProperties(
                docstring=docstring,
                decorators=decorators or [],
                annotations=annotations,
            ),
        )

    @pytest.mark.asyncio
    async def test_enrich_no_metadata(self, enricher: StaticSemanticEnricher) -> None:
        node = self._make_node(docstring="")
        enriched = await enricher.enrich_node(node)
        assert enriched.semantic.status == "no_metadata"
        assert enriched.semantic.source_hash != ""

    @pytest.mark.asyncio
    async def test_enrich_with_docstring(self, enricher: StaticSemanticEnricher) -> None:
        node = self._make_node(docstring="Validates credentials and issues JWT.")
        enriched = await enricher.enrich_node(node)
        assert enriched.semantic.status == "enriched"
        assert enriched.semantic.source_hash != ""
        assert enriched.semantic.enriched_at != ""

    @pytest.mark.asyncio
    async def test_enrich_with_decorators(self, enricher: StaticSemanticEnricher) -> None:
        node = self._make_node(decorators=["pytest.fixture"])
        enriched = await enricher.enrich_node(node)
        assert enriched.semantic.status == "enriched"

    @pytest.mark.asyncio
    async def test_enrich_with_annotations(self, enricher: StaticSemanticEnricher) -> None:
        node = self._make_node(
            annotations=Annotations(params={"x": "int"}, returns="str"),
        )
        enriched = await enricher.enrich_node(node)
        assert enriched.semantic.status == "enriched"

    @pytest.mark.asyncio
    async def test_skip_unchanged(self, enricher: StaticSemanticEnricher) -> None:
        node = self._make_node(docstring="Test.")
        enriched1 = await enricher.enrich_node(node)
        assert enriched1.semantic.status == "enriched"
        hash1 = enriched1.semantic.source_hash

        enriched2 = await enricher.enrich_node(enriched1)
        assert enriched2.semantic.source_hash == hash1

    @pytest.mark.asyncio
    async def test_force_re_enrich(self, enricher: StaticSemanticEnricher) -> None:
        node = self._make_node(docstring="Test.")
        enriched1 = await enricher.enrich_node(node)
        enriched2 = await enricher.enrich_node(enriched1, force=True)
        assert enriched2.semantic.status == "enriched"

    @pytest.mark.asyncio
    async def test_enrich_batch(self, enricher: StaticSemanticEnricher) -> None:
        nodes = [
            self._make_node(id=f"test::Function::f{i}::{i}", name=f"f{i}", docstring=f"Doc {i}.") for i in range(5)
        ]
        enriched = await enricher.enrich_batch(nodes)
        assert len(enriched) == 5
        for n in enriched:
            assert n.semantic.status == "enriched"

    @pytest.mark.asyncio
    async def test_embed_noop(self, enricher: StaticSemanticEnricher) -> None:
        emb = await enricher.embed("test text")
        assert emb == []

    @pytest.mark.asyncio
    async def test_no_llm(self, enricher: StaticSemanticEnricher) -> None:
        assert enricher.has_llm is False

    @pytest.mark.asyncio
    async def test_counts(self, enricher: StaticSemanticEnricher) -> None:
        node = self._make_node(docstring="Test.")
        await enricher.enrich_node(node)
        counts = enricher.get_counts()
        assert counts["enriched"] == 1

    @pytest.mark.asyncio
    async def test_reset_counts(self, enricher: StaticSemanticEnricher) -> None:
        node = self._make_node(docstring="Test.")
        await enricher.enrich_node(node)
        enricher.reset_counts()
        counts = enricher.get_counts()
        assert counts["enriched"] == 0
