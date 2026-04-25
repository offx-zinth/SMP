"""Scale benchmark for :class:`MMapGraphStore`.

Run directly with::

    python3.11 -m benchmarks.benchmark_scale [--nodes 10000] [--depth 3]

The benchmark generates a synthetic graph (linear chain plus random fan-out
edges), measures index/CRUD/traversal latency, and prints a small report.
It deliberately avoids ``pytest-benchmark`` so it can be invoked from the
plain CLI without additional dev dependencies.

Performance targets (see ``SPEC.md``):

* Index lookup: <1ms point query
* Traverse depth 3: <50ms BFS with early exit
* Subsequent queries on hot data: <10ms
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import tempfile
import time
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from smp.core.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    StructuralProperties,
)
from smp.store.graph.mmap_store import MMapGraphStore


def _make_node(idx: int) -> GraphNode:
    name = f"f{idx}"
    return GraphNode(
        id=f"bench::Function::{name}::{idx}",
        type=NodeType.FUNCTION,
        file_path=f"bench/{idx % 100}.py",
        structural=StructuralProperties(
            name=name,
            file=f"bench/{idx % 100}.py",
            signature=f"def {name}():",
            start_line=idx,
            end_line=idx + 2,
        ),
    )


def _make_edge(src: int, dst: int) -> GraphEdge:
    return GraphEdge(
        source_id=f"bench::Function::f{src}::{src}",
        target_id=f"bench::Function::f{dst}::{dst}",
        type=EdgeType.CALLS,
    )


async def _time_async(label: str, fn: Callable[[], Coroutine[Any, Any, Any]]) -> float:
    start = time.perf_counter()
    await fn()
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    print(f"  {label:<32s} {elapsed_ms:>10.2f} ms")
    return elapsed_ms


async def _time_many(
    label: str,
    fn: Callable[[int], Coroutine[Any, Any, Any]],
    iterations: int,
) -> dict[str, float]:
    samples: list[float] = []
    for i in range(iterations):
        start = time.perf_counter()
        await fn(i)
        samples.append((time.perf_counter() - start) * 1000.0)
    p50 = statistics.median(samples)
    p95 = statistics.quantiles(samples, n=20)[18] if len(samples) >= 20 else max(samples)
    print(f"  {label:<32s} p50={p50:>7.3f} ms  p95={p95:>7.3f} ms  n={iterations}")
    return {"p50_ms": p50, "p95_ms": p95}


async def run_benchmark(node_count: int, depth: int) -> None:
    rng = random.Random(0xC0DE)
    fanout = 4

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "bench.smpg"
        store = MMapGraphStore(db_path)
        await store.connect()

        try:
            print(f"\nMMapGraphStore scale benchmark — {node_count} nodes")
            print("-" * 60)

            nodes = [_make_node(i) for i in range(node_count)]

            await _time_async(
                f"upsert_nodes ({node_count})",
                lambda: store.upsert_nodes(nodes),
            )

            edges: list[GraphEdge] = []
            for i in range(node_count - 1):
                edges.append(_make_edge(i, i + 1))
            for i in range(node_count):
                for _ in range(fanout - 1):
                    j = rng.randrange(node_count)
                    if j != i:
                        edges.append(_make_edge(i, j))

            await _time_async(
                f"upsert_edges ({len(edges)})",
                lambda: store.upsert_edges(edges),
            )

            target_ids = [_make_node(rng.randrange(node_count)).id for _ in range(1000)]

            await _time_many(
                "get_node (point lookup)",
                lambda i: store.get_node(target_ids[i]),
                iterations=len(target_ids),
            )

            await _time_many(
                f"traverse depth {depth}",
                lambda i: store.traverse(
                    target_ids[i % len(target_ids)],
                    EdgeType.CALLS,
                    depth=depth,
                    max_nodes=200,
                ),
                iterations=200,
            )

            await _time_async("count_nodes", store.count_nodes)
            await _time_async("count_edges", store.count_edges)

            await _time_async(
                "find_nodes (type filter)",
                lambda: store.find_nodes(type=NodeType.FUNCTION),
            )
        finally:
            await store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="MMapGraphStore scale benchmark")
    parser.add_argument("--nodes", type=int, default=10_000, help="Number of nodes to generate")
    parser.add_argument("--depth", type=int, default=3, help="Traversal depth")
    args = parser.parse_args()
    asyncio.run(run_benchmark(args.nodes, args.depth))


if __name__ == "__main__":
    main()
