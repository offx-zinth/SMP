"""Tests for the DefaultQueryEngine BM25 corpus cache (locate / locate_paged).

Covers: fast-path correctness and ordering, revision-based cache invalidation
after upsert_node / delete_node, classic-path filtering for node_types, and
cache-vs-scan equivalence (guards against semantic drift between the cached
fast path and the original per-query corpus scan).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from smp.core.models import GraphNode, NodeType, SemanticProperties, StructuralProperties
from smp.engine.bm25 import count_matches
from smp.engine.query import DefaultQueryEngine
from smp.store.graph.mmap_store import MMapGraphStore

_RESULT_KEYS = {
    "entity",
    "id",
    "file",
    "file_path",
    "type",
    "matched_on",
    "docstring",
    "tags",
    "signature",
    "start_line",
    "end_line",
    "lines",
    "score",
}


def _node(
    node_id: str,
    node_type: NodeType = NodeType.FUNCTION,
    name: str = "",
    file_path: str = "file.py",
    docstring: str = "",
    tags: list[str] | None = None,
) -> GraphNode:
    return GraphNode(
        id=node_id,
        type=node_type,
        file_path=file_path,
        structural=StructuralProperties(
            name=name or node_id,
            file=file_path,
            signature=f"def {name or node_id}():",
            start_line=1,
            end_line=10,
            lines=10,
        ),
        semantic=SemanticProperties(
            docstring=docstring,
            status="enriched" if docstring else "no_metadata",
            tags=tags or [],
        ),
    )


@pytest.fixture()
async def store(tmp_path: Path) -> AsyncIterator[MMapGraphStore]:
    """A connected MMapGraphStore in a throwaway file (mirrors tests/conftest)."""
    graph = MMapGraphStore(path=str(tmp_path / "locate_corpus.graph.smpg"))
    await graph.connect()
    try:
        yield graph
    finally:
        await graph.close()


async def _seed(corpus: MMapGraphStore) -> None:
    """Standard three-symbol graph the cache tests share."""
    await corpus.upsert_nodes(
        [
            _node(
                "alpha_parse_id",
                NodeType.FUNCTION,
                "alpha_parse",
                "alpha.py",
                docstring="parse the alpha input payload",
            ),
            _node(
                "alpha_run_id",
                NodeType.FUNCTION,
                "alpha_run",
                "alpha.py",
                docstring="run the alpha pipeline",
            ),
            _node(
                "beta_parse_id",
                NodeType.FUNCTION,
                "beta_parse",
                "beta.py",
                docstring="parse beta config",
            ),
        ]
    )


class TestLocateFastPath:
    async def test_exact_name_outranks_fuzzy_matches(self, store: MMapGraphStore) -> None:
        await _seed(store)
        engine = DefaultQueryEngine(store)

        results = await engine.locate("alpha_parse")

        assert results, "expected at least one match"
        assert results[0]["entity"] == "alpha_parse"
        assert results[0]["matched_on"] == "name (exact)"
        entities = [r["entity"] for r in results]
        # The exact-name hit must beat the fuzzy token matches, and both
        # fuzzily-related nodes stay reachable on the same query.
        assert {"alpha_run", "beta_parse"} <= set(entities)
        assert results == sorted(results, key=lambda r: -r["score"])

    async def test_result_payload_shape(self, store: MMapGraphStore) -> None:
        await _seed(store)
        engine = DefaultQueryEngine(store)

        results = await engine.locate("alpha_parse")

        assert set(results[0]) == _RESULT_KEYS
        assert isinstance(results[0]["tags"], list)
        assert isinstance(results[0]["score"], float)
        assert results[0]["file_path"] == "alpha.py"
        # Cache was built and is holding rows (fast path engaged).
        assert engine._corpus_cache is not None and engine._corpus_cache[2]

    async def test_no_match_returns_empty(self, store: MMapGraphStore) -> None:
        await _seed(store)
        engine = DefaultQueryEngine(store)

        assert await engine.locate("zzz_unrelated") == []


class TestRevisionInvalidation:
    async def test_upsert_bumps_revision_and_locate_sees_new_node(self, store: MMapGraphStore) -> None:
        await _seed(store)
        engine = DefaultQueryEngine(store)
        # Warm the cache, and confirm the future node is not served early.
        assert await engine.locate("gamma_helper") == []
        revision_before = store.revision

        await store.upsert_node(
            _node(
                "gamma_helper_id",
                NodeType.FUNCTION,
                "gamma_helper",
                "gamma.py",
                docstring="helper for the gamma run",
            )
        )

        assert store.revision > revision_before, "upsert_node must bump store.revision"
        results = await engine.locate("gamma_helper")
        assert results, "fresh node must be found after revision bump"
        assert results[0]["entity"] == "gamma_helper"

    async def test_delete_removes_node_from_cached_results(self, store: MMapGraphStore) -> None:
        await _seed(store)
        engine = DefaultQueryEngine(store)
        initial = await engine.locate("alpha_parse")
        assert any(r["entity"] == "alpha_parse" for r in initial)
        revision_before = store.revision

        deleted = await store.delete_node("alpha_parse_id")

        assert deleted is True
        assert store.revision > revision_before, "delete_node must bump store.revision"
        results = await engine.locate("alpha_parse")
        # The exact-name hit is gone; only the fuzzy token matches remain.
        assert {r["entity"] for r in results} == {"alpha_run", "beta_parse"}


class TestClassicPath:
    async def test_node_types_filter_returns_only_filtered_type(self, store: MMapGraphStore) -> None:
        await _seed(store)
        await store.upsert_node(
            _node(
                "beta_cls_id",
                NodeType.CLASS,
                "BetaParser",
                "beta.py",
                # "parse" must appear as a standalone token: score_node only
                # scores terms present in the corpus IDF map (substring-only
                # presence is not scored) — faithful to the scan path.
                docstring="class doing beta parse tasks",
                tags=["parser"],
            )
        )
        engine = DefaultQueryEngine(store)

        filtered = await engine.locate("parse", node_types=["Class"])
        unfiltered = await engine.locate("parse")

        assert filtered, "expected class matches"
        assert {r["type"] for r in filtered} == {"Class"}
        assert {r["entity"] for r in filtered} == {"BetaParser"}
        assert len(unfiltered) > len(filtered), "filter must remove some results"


class TestCacheEquivalence:
    @staticmethod
    def _uncached_engine(store: MMapGraphStore) -> DefaultQueryEngine:
        """Engine with the cache disabled so every query takes the scan path."""
        engine = DefaultQueryEngine(store)
        # Shift the size budget to 0 so _get_corpus_cache always returns the
        # oversized sentinel (None) and callers fall back to bm25.build_corpus.
        engine._corpus_cache_max_nodes = 0
        return engine

    async def test_locate_cached_equals_uncached_scan(self, store: MMapGraphStore) -> None:
        await _seed(store)
        warm = DefaultQueryEngine(store)
        scan = self._uncached_engine(store)

        cases: list[tuple[str, dict[str, object]]] = [
            ("alpha_parse", {}),
            ("parse", {}),
            ("alpha parse", {"match": "all"}),
            ("alpha parse", {}),
            ("parse", {"top_k": 1, "offset": 1}),
            ("alpha_parse", {"top_k": 0}),
            ("zzz_unrelated", {}),
        ]
        for query, kwargs in cases:
            cached_result = await warm.locate(query, **kwargs)  # type: ignore[arg-type]
            scan_result = await scan.locate(query, **kwargs)  # type: ignore[arg-type]
            assert cached_result == scan_result, f"drift for {query!r} {kwargs}"

    async def test_locate_paged_cached_equals_uncached(self, store: MMapGraphStore) -> None:
        await _seed(store)
        warm = DefaultQueryEngine(store)
        scan = self._uncached_engine(store)

        for query, kwargs in (("parse", {}), ("alpha_parse", {"match": "all"})):
            paged_warm = await warm.locate_paged(query, **kwargs)  # type: ignore[arg-type]
            paged_scan = await scan.locate_paged(query, **kwargs)  # type: ignore[arg-type]
            assert paged_warm == paged_scan, f"paged drift for {query!r}"

        assert "matches" in paged_warm
        assert "total" in paged_warm
        assert "has_more" in paged_warm
        # Independent oracle: total must equal bm25.count_matches over the store.
        nodes = await store.find_nodes()
        assert paged_warm["total"] == count_matches("alpha_parse", nodes, match="all")

    async def test_warm_cache_skips_find_nodes_probe(self, store: MMapGraphStore) -> None:
        await _seed(store)
        probes: list[int] = []
        original = store.find_nodes

        async def counting(**kwargs: Any) -> list[GraphNode]:
            probes.append(1)
            return await original(**kwargs)

        store.find_nodes = counting  # type: ignore[method-assign]
        try:
            engine = DefaultQueryEngine(store)
            await engine.locate("alpha_parse")  # builds the cache once
            after_build = len(probes)
            assert after_build == 1

            await engine.locate("alpha_parse")
            await engine.locate("alpha_run")
            await engine.locate_paged("alpha_run")
            assert len(probes) == after_build, "warm cache must not re-probe find_nodes"
        finally:
            del store.find_nodes  # restore the bound method
