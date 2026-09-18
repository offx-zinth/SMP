from __future__ import annotations

import asyncio
import random
import time
import uuid
from typing import Any

import pytest

from smp.engine.query import DefaultQueryEngine
from smp.protocol.handlers import memory, query, vector


async def run_stress_session(ctx: dict[str, Any], ops_count: int, op_type: str):
    """Perform a sequence of operations in a single session."""
    start_time = time.perf_counter()

    for i in range(ops_count):
        if op_type == "read":
            await query.navigate({"query": f"node_{i % 100}", "include_relationships": True}, ctx)
        elif op_type == "write":
            await memory.update({"file_path": f"src/file_{i % 100}.py"}, ctx)
        elif op_type == "vector":
            embedding = [random.uniform(-1, 1) for _ in range(128)]
            await vector.vector_upsert(
                {
                    "ids": [str(uuid.uuid4())],
                    "embeddings": [embedding],
                    "metadatas": [{"type": "stress"}],
                    "documents": [f"Stress doc {i}"],
                },
                ctx,
            )
        elif op_type == "mixed":
            op = random.choice(["read", "write", "vector"])
            if op == "read":
                await query.navigate({"query": f"node_{i % 100}", "include_relationships": True}, ctx)
            elif op == "write":
                await memory.update({"file_path": f"src/file_{i % 100}.py"}, ctx)
            else:
                embedding = [random.uniform(-1, 1) for _ in range(128)]
                await vector.vector_upsert(
                    {
                        "ids": [str(uuid.uuid4())],
                        "embeddings": [embedding],
                        "metadatas": [{"type": "stress"}],
                        "documents": [f"Stress doc {i}"],
                    },
                    ctx,
                )

    return time.perf_counter() - start_time


@pytest.mark.asyncio
async def test_stress_read_session(populated_graph_store):
    """Stress test: 1000 read operations."""
    engine = DefaultQueryEngine(graph_store=populated_graph_store)
    ctx = {"engine": engine, "graph": populated_graph_store}
    duration = await run_stress_session(ctx, 1000, "read")
    assert duration > 0


@pytest.mark.asyncio
async def test_stress_write_session(populated_graph_store):
    """Stress test: 1000 write operations."""
    ctx = {"graph": populated_graph_store}
    duration = await run_stress_session(ctx, 1000, "write")
    assert duration > 0


@pytest.mark.asyncio
async def test_stress_vector_session(populated_vector_store):
    """Stress test: 1000 vector operations."""
    ctx = {"vector_store": populated_vector_store}
    duration = await run_stress_session(ctx, 1000, "vector")
    assert duration > 0


@pytest.mark.asyncio
async def test_stress_mixed_session(populated_graph_store, populated_vector_store):
    """Stress test: 1000 mixed operations."""
    engine = DefaultQueryEngine(graph_store=populated_graph_store)
    ctx = {"engine": engine, "graph": populated_graph_store, "vector_store": populated_vector_store}
    duration = await run_stress_session(ctx, 1000, "mixed")
    assert duration > 0


# Adding a few more variations to reach 10 tests
@pytest.mark.asyncio
async def test_stress_read_heavy_session(populated_graph_store):
    """Stress test: 1000 read operations with varying depth."""
    engine = DefaultQueryEngine(graph_store=populated_graph_store)
    ctx = {"engine": engine}

    start_time = time.perf_counter()
    for i in range(1000):
        await query.trace(
            {"start": f"func_{i % 100}", "relationship": "calls", "depth": random.randint(1, 5), "direction": "out"},
            ctx,
        )
    duration = time.perf_counter() - start_time
    assert duration > 0


@pytest.mark.asyncio
async def test_stress_write_heavy_session(populated_graph_store):
    """Stress test: 1000 batch updates."""
    ctx = {"graph": populated_graph_store}

    start_time = time.perf_counter()
    for _ in range(100):  # 100 * 10 = 1000
        await memory.batch_update({"changes": [{"file_path": f"src/file_{j}.py"} for j in range(10)]}, ctx)
    duration = time.perf_counter() - start_time
    assert duration > 0


@pytest.mark.asyncio
async def test_stress_vector_heavy_session(populated_vector_store):
    """Stress test: 1000 vector searches."""
    ctx = {"vector_store": populated_vector_store}

    start_time = time.perf_counter()
    for _ in range(1000):
        embedding = [random.uniform(-1, 1) for _ in range(128)]
        await vector.vector_search({"embedding": embedding, "top_k": 10, "where": {}}, ctx)
    duration = time.perf_counter() - start_time
    assert duration > 0


@pytest.mark.asyncio
async def test_stress_concurrent_read_session(populated_graph_store):
    """Stress test: 1000 concurrent reads in batches."""
    engine = DefaultQueryEngine(graph_store=populated_graph_store)
    ctx = {"engine": engine}

    start_time = time.perf_counter()
    for i in range(0, 1000, 50):
        tasks = [
            query.navigate({"query": f"node_{j % 100}", "include_relationships": True}, ctx) for j in range(i, i + 50)
        ]
        await asyncio.gather(*tasks)
    duration = time.perf_counter() - start_time
    assert duration > 0


@pytest.mark.asyncio
async def test_stress_mixed_concurrent_session(populated_graph_store, populated_vector_store):
    """Stress test: 1000 mixed concurrent operations."""
    engine = DefaultQueryEngine(graph_store=populated_graph_store)
    ctx = {"engine": engine, "graph": populated_graph_store, "vector_store": populated_vector_store}

    start_time = time.perf_counter()
    for i in range(0, 1000, 50):
        tasks = []
        for j in range(i, i + 50):
            op = random.choice(["read", "write", "vector"])
            if op == "read":
                tasks.append(query.navigate({"query": f"node_{j % 100}", "include_relationships": True}, ctx))
            elif op == "write":
                tasks.append(memory.update({"file_path": f"src/file_{j % 100}.py"}, ctx))
            else:
                embedding = [random.uniform(-1, 1) for _ in range(128)]
                tasks.append(
                    vector.vector_upsert(
                        {
                            "ids": [str(uuid.uuid4())],
                            "embeddings": [embedding],
                            "metadatas": [{"type": "stress"}],
                            "documents": [f"Stress doc {j}"],
                        },
                        ctx,
                    )
                )
        await asyncio.gather(*tasks)
    duration = time.perf_counter() - start_time
    assert duration > 0
