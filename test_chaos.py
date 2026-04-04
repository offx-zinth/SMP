"""Chaos Tests — validate cross-file impact analysis across 3 scenarios.

Run:  python test_chaos.py
"""

from __future__ import annotations

import asyncio
import time

from smp.engine.graph_builder import DefaultGraphBuilder
from smp.engine.query import DefaultQueryEngine
from smp.parser.registry import ParserRegistry
from smp.store.graph.neo4j_store import Neo4jGraphStore


class _DummyVectorStore:
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def clear(self) -> None: ...
    async def upsert(self, **_: object) -> None: ...
    async def query(self, **_: object) -> list: return []
    async def get(self, **_: object) -> list: return []
    async def delete(self, **_: object) -> int: return 0
    async def delete_by_file(self, **_: object) -> int: return 0


TEST_DIR = "smp/demo/chaos_tests"


async def setup() -> tuple[Neo4jGraphStore, DefaultGraphBuilder, DefaultQueryEngine]:
    """Clear graph, ingest chaos test files, return connected stores."""
    registry = ParserRegistry()
    store = Neo4jGraphStore()
    builder = DefaultGraphBuilder(store)
    await store.connect()
    await store.clear()

    import os
    for fname in sorted(os.listdir(TEST_DIR)):
        fpath = os.path.join(TEST_DIR, fname)
        if not fname.endswith(".py") or fname.startswith("__"):
            continue
        doc = registry.parse_file(fpath)
        await builder.ingest_document(doc)

    # Resolve any pending cross-file edges
    await builder.resolve_pending_edges()

    engine = DefaultQueryEngine(store, _DummyVectorStore())
    return store, builder, engine


def header(num: str, title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  TEST {num}: {title}")
    print(f"{'='*60}")


# ──────────────────────────────────────────────────────────────
# TEST 1 — Grandfather Ripple (Deep Transitivity)
# ──────────────────────────────────────────────────────────────

async def test_grandfather_ripple(store: Neo4jGraphStore, engine: DefaultQueryEngine) -> bool:
    header("1", "Grandfather Ripple — deep A→B→C transitivity")

    # Show the call chain
    print("\nCall chain:")
    print("  grandfather.py::base_func  ←  father.py::mid_func  ←  child.py::top_func")

    # Show all CALLS edges for the chaos_tests files
    from smp.core.models import EdgeType
    records = await store._execute(
        "MATCH (a)-[r:CALLS]->(b) "
        "WHERE a.file_path CONTAINS 'chaos_tests' "
        "RETURN a.id AS src, b.id AS tgt ORDER BY src"
    )
    print("\nGraph edges:")
    for r in records:
        print(f"  {r['src']}  →  {r['tgt']}")

    # Impact on base_func (the grandfather) — look up by name
    candidates = await store.find_nodes(name="base_func")
    if not candidates:
        print(f"\n  ✗ FAIL — base_func node not found in graph")
        return False

    target = candidates[0].id
    print(f"\n  Target node: {target}")

    impact = await engine.assess_impact(target, depth=10)
    affected = impact.get("affected_nodes", [])
    total = impact.get("total_affected", 0)

    print(f"\n  Impact on base_func (depth=10):")
    print(f"    Total affected: {total}")
    for a in affected:
        print(f"    - {a['type']}: {a['name']} in {a['file_path']}")

    affected_names = {a["name"] for a in affected}
    has_mid = "mid_func" in affected_names
    has_top = "top_func" in affected_names

    print(f"\n  mid_func  affected?  {'✓' if has_mid else '✗'}")
    print(f"  top_func  affected?  {'✓' if has_top else '✗'}  (transitive)")

    ok = has_mid and has_top and total >= 2
    print(f"\n  {'✓ PASS' if ok else '✗ FAIL'} — transitive impact detected {total} levels deep")
    return ok


# ──────────────────────────────────────────────────────────────
# TEST 2 — Interface Contract (One-to-Many)
# ──────────────────────────────────────────────────────────────

async def test_interface_contract(store: Neo4jGraphStore, engine: DefaultQueryEngine) -> bool:
    header("2", "Interface Contract — one function, many callers")

    print("\nShared contract: validate_payload")
    print("  Used by: plugin_a::process_order, plugin_b::process_payment, plugin_c::process_shipment")

    from smp.core.models import EdgeType
    records = await store._execute(
        "MATCH (a)-[r:CALLS]->(b) "
        "WHERE a.file_path CONTAINS 'chaos_tests' AND a.file_path CONTAINS 'plugin' "
        "RETURN a.id AS src, b.id AS tgt ORDER BY src"
    )
    print("\nGraph edges (plugins):")
    for r in records:
        print(f"  {r['src']}  →  {r['tgt']}")

    candidates = await store.find_nodes(name="validate_payload")
    if not candidates:
        print(f"\n  ✗ FAIL — validate_payload node not found")
        return False

    target = candidates[0].id
    print(f"\n  Target node: {target}")

    impact = await engine.assess_impact(target, depth=10)
    affected = impact.get("affected_nodes", [])
    total = impact.get("total_affected", 0)

    print(f"\n  Impact on validate_payload:")
    print(f"    Total affected: {total}")
    for a in affected:
        print(f"    - {a['type']}: {a['name']} in {a['file_path']}")

    affected_names = {a["name"] for a in affected}
    has_a = "process_order" in affected_names
    has_b = "process_payment" in affected_names
    has_c = "process_shipment" in affected_names

    print(f"\n  process_order    affected?  {'✓' if has_a else '✗'}")
    print(f"  process_payment  affected?  {'✓' if has_b else '✗'}")
    print(f"  process_shipment affected?  {'✓' if has_c else '✗'}")

    ok = has_a and has_b and has_c and total >= 3
    print(f"\n  {'✓ PASS' if ok else '✗ FAIL'} — all {total} dependents detected")
    return ok


# ──────────────────────────────────────────────────────────────
# TEST 3 — Infinite Loop (Circular Imports)
# ──────────────────────────────────────────────────────────────

async def test_circular_imports(store: Neo4jGraphStore, engine: DefaultQueryEngine) -> bool:
    header("3", "Infinite Loop — circular imports stress test")

    print("\nCircular chain:")
    print("  alpha.py::alpha_func  ⟷  beta.py::beta_func")

    from smp.core.models import EdgeType
    records = await store._execute(
        "MATCH (a)-[r:CALLS]->(b) "
        "WHERE a.file_path CONTAINS 'chaos_tests' AND (a.file_path CONTAINS 'alpha' OR a.file_path CONTAINS 'beta') "
        "RETURN a.id AS src, b.id AS tgt ORDER BY src"
    )
    print("\nGraph edges:")
    for r in records:
        print(f"  {r['src']}  →  {r['tgt']}")

    # Test impact on alpha_func — must not hang or crash
    candidates = await store.find_nodes(name="alpha_func")
    if not candidates:
        print(f"\n  ✗ FAIL — alpha_func node not found")
        return False

    target_alpha = candidates[0].id
    print(f"\n  Target node: {target_alpha}")

    print("\n  Running impact on alpha_func (timeout-safe)...")
    t0 = time.monotonic()
    try:
        impact = await asyncio.wait_for(
            engine.assess_impact(target_alpha, depth=10),
            timeout=10.0,
        )
    except asyncio.TimeoutError:
        print(f"  ✗ FAIL — assess_impact timed out (infinite loop detected!)")
        return False
    elapsed = round(time.monotonic() - t0, 3)

    affected = impact.get("affected_nodes", [])
    total = impact.get("total_affected", 0)

    print(f"    Completed in {elapsed}s  (no hang)")
    print(f"    Total affected: {total}")
    for a in affected:
        print(f"    - {a['type']}: {a['name']} in {a['file_path']}")

    affected_names = {a["name"] for a in affected}
    has_beta = "beta_func" in affected_names

    print(f"\n  beta_func  affected?  {'✓' if has_beta else '✗'}")

    # Now test impact on beta_func too
    candidates2 = await store.find_nodes(name="beta_func")
    has_alpha = False
    if candidates2:
        target_beta = candidates2[0].id
        print(f"  Target node: {target_beta}")
        print("\n  Running impact on beta_func (timeout-safe)...")
        t0 = time.monotonic()
        try:
            impact2 = await asyncio.wait_for(
                engine.assess_impact(target_beta, depth=10),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            print(f"  ✗ FAIL — assess_impact on beta_func timed out!")
            return False
        elapsed2 = round(time.monotonic() - t0, 3)

        affected2 = impact2.get("affected_nodes", [])
        total2 = impact2.get("total_affected", 0)

        print(f"    Completed in {elapsed2}s  (no hang)")
        print(f"    Total affected: {total2}")
        for a in affected2:
            print(f"    - {a['type']}: {a['name']} in {a['file_path']}")

        affected_names2 = {a["name"] for a in affected2}
        has_alpha = "alpha_func" in affected_names2
        print(f"\n  alpha_func  affected?  {'✓' if has_alpha else '✗'}")

    ok = has_beta and has_alpha and elapsed < 5.0
    print(f"\n  {'✓ PASS' if ok else '✗ FAIL'} — circular handled gracefully, no crash")
    return ok


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

async def main() -> None:
    print("\n" + "=" * 60)
    print("  SMP CHAOS TESTS — Cross-File Impact Analysis")
    print("=" * 60)

    store, builder, engine = await setup()

    results: dict[str, bool] = {}

    try:
        results["1_grandfather"] = await test_grandfather_ripple(store, engine)
        results["2_contract"] = await test_interface_contract(store, engine)
        results["3_circular"] = await test_circular_imports(store, engine)
    finally:
        await store.close()

    # Summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    for name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}  {name}")

    all_pass = all(results.values())
    print(f"\n  {'✓ ALL TESTS PASSED' if all_pass else '✗ SOME TESTS FAILED'}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
