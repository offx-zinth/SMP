"""Mega-Monorepo — Final Boss Test.

Ingests the entire mega_test/ tree and runs 4 impact assessments.
"""

from __future__ import annotations

import asyncio
import os
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


TEST_DIR = "smp/demo/mega_test"


async def setup() -> tuple[Neo4jGraphStore, DefaultGraphBuilder, DefaultQueryEngine]:
    registry = ParserRegistry()
    store = Neo4jGraphStore()
    builder = DefaultGraphBuilder(store)
    await store.connect()
    await store.clear()

    file_count = 0
    for root, _dirs, files in os.walk(TEST_DIR):
        for fname in sorted(files):
            if not fname.endswith(".py") or fname.startswith("__"):
                continue
            fpath = os.path.join(root, fname)
            doc = registry.parse_file(fpath)
            await builder.ingest_document(doc)
            file_count += 1

    await builder.resolve_pending_edges()

    total_nodes = await store.count_nodes()
    total_edges = await store.count_edges()
    print(f"\n  Ingested {file_count} files → {total_nodes} nodes, {total_edges} edges")

    engine = DefaultQueryEngine(store, _DummyVectorStore())
    return store, builder, engine


async def impact_by_name(engine: DefaultQueryEngine, store: Neo4jGraphStore, name: str) -> dict:
    """Run impact for the first node with the given name."""
    cands = await store.find_nodes(name=name)
    if not cands:
        return {"error": f"'{name}' not found", "affected_nodes": [], "total_affected": 0}
    target = cands[0].id
    return await engine.assess_impact(target, depth=15)


def banner(title: str) -> None:
    print(f"\n{'━'*60}")
    print(f"  {title}")
    print(f"{'━'*60}")


async def main() -> None:
    print("\n" + "█" * 60)
    print("  SMP MEGA-MONOREPO — FINAL BOSS TEST")
    print("█" * 60)

    store, builder, engine = await setup()

    # Show all CALLS edges for overview
    records = await store._execute(
        "MATCH (a)-[r:CALLS]->(b) RETURN a.id AS src, b.id AS tgt ORDER BY src"
    )
    print(f"\n  Total CALLS edges: {len(records)}")
    for r in records:
        src_short = r["src"].replace("smp/demo/mega_test/", "")
        tgt_short = r["tgt"].replace("smp/demo/mega_test/", "")
        print(f"    {src_short}  →  {tgt_short}")

    # ══════════════════════════════════════════════════════════
    # CHANGE 1: low_level_query — add connection_pool param
    # ══════════════════════════════════════════════════════════
    banner("CHANGE 1: infra/database.py::low_level_query — add connection_pool param")

    t0 = time.monotonic()
    impact1 = await impact_by_name(engine, store, "low_level_query")
    elapsed1 = round(time.monotonic() - t0, 3)

    affected1 = impact1.get("affected_nodes", [])
    print(f"\n  Target: low_level_query")
    print(f"  Affected: {impact1.get('total_affected', 0)}  ({elapsed1}s)")
    names1 = set()
    for a in affected1:
        short = a["file_path"].replace("smp/demo/mega_test/", "")
        names1.add(a["name"])
        print(f"    ├─ {a['name']:25s}  ({short})")
    print(f"  UNIQUE AFFECTED FUNCTIONS: {len(names1)}")

    # ══════════════════════════════════════════════════════════
    # CHANGE 2: format_data_value — return JSON string
    # ══════════════════════════════════════════════════════════
    banner("CHANGE 2: utils/formatter.py::format_data_value — return JSON string")

    t0 = time.monotonic()
    impact2 = await impact_by_name(engine, store, "format_data_value")
    elapsed2 = round(time.monotonic() - t0, 3)

    affected2 = impact2.get("affected_nodes", [])
    print(f"\n  Target: format_data_value")
    print(f"  Affected: {impact2.get('total_affected', 0)}  ({elapsed2}s)")
    names2 = set()
    for a in affected2:
        short = a["file_path"].replace("smp/demo/mega_test/", "")
        names2.add(a["name"])
        print(f"    ├─ {a['name']:25s}  ({short})")
    print(f"  UNIQUE AFFECTED FUNCTIONS: {len(names2)}")

    # ══════════════════════════════════════════════════════════
    # CHANGE 3: raw_gpio_write → rename to secure_hw_dispatch
    # ══════════════════════════════════════════════════════════
    banner("CHANGE 3: infra/hardware.py::raw_gpio_write — rename to secure_hw_dispatch")

    t0 = time.monotonic()
    impact3 = await impact_by_name(engine, store, "raw_gpio_write")
    elapsed3 = round(time.monotonic() - t0, 3)

    affected3 = impact3.get("affected_nodes", [])
    print(f"\n  Target: raw_gpio_write")
    print(f"  Affected: {impact3.get('total_affected', 0)}  ({elapsed3}s)")
    names3 = set()
    for a in affected3:
        short = a["file_path"].replace("smp/demo/mega_test/", "")
        names3.add(a["name"])
        print(f"    ├─ {a['name']:25s}  ({short})")
    print(f"  UNIQUE AFFECTED FUNCTIONS: {len(names3)}")

    # ══════════════════════════════════════════════════════════
    # CHANGE 4: BaseProcessor.execute_logic — add timeout param
    # ══════════════════════════════════════════════════════════
    banner("CHANGE 4: core/base_engine.py::BaseProcessor.execute_logic — add timeout param")

    # execute_logic is a METHOD on a class — look for it
    cands4 = await store.find_nodes(name="execute_logic")
    target4_id = cands4[0].id if cands4 else None

    t0 = time.monotonic()
    if target4_id:
        impact4 = await engine.assess_impact(target4_id, depth=15)
    else:
        impact4 = {"affected_nodes": [], "total_affected": 0}
    elapsed4 = round(time.monotonic() - t0, 3)

    affected4 = impact4.get("affected_nodes", [])
    print(f"\n  Target: execute_logic")
    print(f"  Affected: {impact4.get('total_affected', 0)}  ({elapsed4}s)")
    names4 = set()
    for a in affected4:
        short = a["file_path"].replace("smp/demo/mega_test/", "")
        names4.add(a["name"])
        print(f"    ├─ {a['name']:25s}  ({short})")
    print(f"  UNIQUE AFFECTED FUNCTIONS: {len(names4)}")

    # ══════════════════════════════════════════════════════════
    # SAFETY ANALYSIS
    # ══════════════════════════════════════════════════════════
    banner("SAFETY ANALYSIS — What can be left alone?")

    all_affected = names1 | names2 | names3 | names4

    # Get all FUNCTION nodes
    from smp.core.models import NodeType
    all_func_nodes = await store.find_nodes(type=NodeType.FUNCTION)
    all_func_names = {n.name for n in all_func_nodes}
    safe = all_func_names - all_affected - {
        "low_level_query", "format_data_value", "raw_gpio_write", "execute_logic",
    }

    print(f"\n  Total functions in monorepo: {len(all_func_names)}")
    print(f"  Functions being changed:    4")
    print(f"  Functions affected:          {len(all_affected)}")
    print(f"  Functions SAFE (untouched):  {len(safe)}")
    print()
    print(f"  SAFE FUNCTIONS:")
    for s in sorted(safe):
        print(f"    ✓ {s}")

    # ══════════════════════════════════════════════════════════
    # FULL DEPENDENCY MAP
    # ══════════════════════════════════════════════════════════
    banner("FULL DEPENDENCY MAP")

    print(f"\n  infra/database.py::low_level_query")
    print(f"    └→ core/user_domain.py::get_user_model")
    print(f"       └→ services/auth_service.py::authenticate_user")
    print(f"          └→ api/gateway.py::handle_login_request")
    print(f"    └→ features/billing.py::save")
    print(f"    └→ features/inventory.py::save")
    print()
    print(f"  utils/formatter.py::format_data_value")
    print(f"    └→ core/data_processor.py::analyze_temperature")
    print(f"       └→ services/analytics_svc.py::generate_report")
    print(f"    └→ core/data_processor.py::analyze_voltage")
    print(f"       └→ services/analytics_svc.py::generate_report")
    print(f"    └→ core/data_processor.py::calculate_balance")
    print(f"       └→ services/analytics_svc.py::generate_report")
    print(f"    └→ chain/step_02 → step_03 → ... → step_10 (8 hops)")
    print()
    print(f"  infra/hardware.py::raw_gpio_write")
    print(f"    └→ core/security.py::trigger_alarm")
    print(f"       └→ api/home_api.py::api_security_emergency")
    print(f"    └→ services/lighting.py::set_bulb_state")
    print(f"       └→ api/home_api.py::api_toggle_lights")
    print()
    print(f"  core/base_engine.py::execute_logic")
    print(f"    └→ services/scheduler.py::run_scheduled_task")

    await store.close()

    # Final verdict
    print(f"\n{'█'*60}")
    print(f"  FINAL VERDICT")
    print(f"{'█'*60}")
    print(f"  Total functions:     {len(all_func_names)}")
    print(f"  Changes:             4")
    print(f"  Blast radius:        {len(all_affected)} functions affected")
    print(f"  Safe to leave alone: {len(safe)} functions")
    print(f"{'█'*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
