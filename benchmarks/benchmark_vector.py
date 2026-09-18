"""Scale benchmark for :class:`MMapVectorStore`.

Run directly with::

    python3.11 -m benchmarks.benchmark_vector [--vectors 10000] [--dim 768]

The benchmark generates synthetic vectors, measures upsert/query latency,
and prints a report.
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

from smp.vector.mmap_vector import MMapVectorStore


def _make_vector(dim: int) -> list[float]:
    return [random.uniform(-1.0, 1.0) for _ in range(dim)]


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


async def run_benchmark(vector_count: int, dim: int) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        vec_path = Path(tmp) / "bench.smpv"
        store = MMapVectorStore(path=str(vec_path), dimension=dim)
        await store.connect()

        try:
            print(f"\nMMapVectorStore scale benchmark — {vector_count} vectors (dim={dim})")
            print("-" * 60)

            ids = [f"vec_{i}" for i in range(vector_count)]
            embeddings = [_make_vector(dim) for _ in range(vector_count)]
            metadatas = [{"idx": i, "file": f"f{i % 100}.py"} for i in range(vector_count)]
            documents = [f"doc content for {i}" for i in range(vector_count)]

            await _time_async(
                f"upsert_vectors ({vector_count})",
                lambda: store.upsert(ids, embeddings, metadatas, documents),
            )

            query_vec = _make_vector(dim)

            await _time_many(
                "cosine_search (top-5)",
                lambda i: store.query(query_vec, top_k=5),
                iterations=100,
            )

            # Test filter
            await _time_many(
                "filtered_search (file=f1.py)",
                lambda i: store.query(query_vec, top_k=5, where={"file": "f1.py"}),
                iterations=100,
            )

            await _time_async(
                "count_vectors",
                lambda: asyncio.sleep(0) or len(store),
            )

        finally:
            await store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="MMapVectorStore scale benchmark")
    parser.add_argument("--vectors", type=int, default=10_000, help="Number of vectors to generate")
    parser.add_argument("--dim", type=int, default=768, help="Embedding dimension")
    args = parser.parse_args()
    asyncio.run(run_benchmark(args.vectors, args.dim))


if __name__ == "__main__":
    main()
