from __future__ import annotations

import asyncio
import random
import time
import uuid

import pytest

from smp.engine.query import DefaultQueryEngine
from smp.protocol.handlers import memory, query, vector


async def measure_throughput(func, params, ctx, concurrent_requests: int, total_requests: int) -> float:
    """Measure requests per second for a given handler."""
    start_time = time.perf_counter()

    # Chunk total requests into concurrent batches
    batch_size = concurrent_requests
    for i in range(0, total_requests, batch_size):
        tasks = [func(params, ctx) for _ in range(min(batch_size, total_requests - i))]
        await asyncio.gather(*tasks)

    end_time = time.perf_counter()
    duration = end_time - start_time
    return total_requests / duration


@pytest.mark.asyncio
async def test_p009_read_throughput(populated_graph_store):
    """P-009: Measure throughput for read operations."""
    engine = DefaultQueryEngine(graph_store=populated_graph_store)
    ctx = {"engine": engine}

    # Test navigate
    nav_params = {"query": "class User", "include_relationships": True}
    nav_tps = await measure_throughput(query.navigate, nav_params, ctx, 10, 100)

    # Test search
    search_params = {"query": "auth", "match": "any", "filter": {}, "top_k": 10}
    search_tps = await measure_throughput(query.search, search_params, ctx, 10, 100)

    # Test context
    ctx_params = {"file_path": "src/auth/login.py", "scope": "function", "depth": 2}
    ctx_tps = await measure_throughput(query.context, ctx_params, ctx, 10, 100)

    assert nav_tps > 0
    assert search_tps > 0
    assert ctx_tps > 0


@pytest.mark.asyncio
async def test_p010_write_throughput(populated_graph_store, populated_vector_store):
    """P-010: Measure throughput for write operations."""
    # Graph update
    graph_ctx = {"graph": populated_graph_store}
    update_params = {"file_path": "src/auth/login.py"}
    update_tps = await measure_throughput(memory.update, update_params, graph_ctx, 5, 50)

    # Vector upsert
    vector_ctx = {"vector_store": populated_vector_store}
    embedding = [random.uniform(-1, 1) for _ in range(128)]
    upsert_params = {
        "ids": [str(uuid.uuid4())],
        "embeddings": [embedding],
        "metadatas": [{"type": "code_chunk"}],
        "documents": ["some code snippet"],
    }
    upsert_tps = await measure_throughput(vector.vector_upsert, upsert_params, vector_ctx, 5, 50)

    assert update_tps > 0
    assert upsert_tps > 0


@pytest.mark.asyncio
async def test_p011_mixed_throughput(populated_graph_store, populated_vector_store):
    """P-011: Measure throughput for mixed operations."""
    engine = DefaultQueryEngine(graph_store=populated_graph_store)
    graph_ctx = {"graph": populated_graph_store, "engine": engine}
    vector_ctx = {"vector_store": populated_vector_store}

    async def mixed_op() -> None:
        op = random.choice(["read", "write_graph", "write_vector"])
        if op == "read":
            await query.navigate({"query": "class User", "include_relationships": True}, graph_ctx)
        elif op == "write_graph":
            await memory.update({"file_path": "src/auth/login.py"}, graph_ctx)
        else:
            embedding = [random.uniform(-1, 1) for _ in range(128)]
            await vector.vector_upsert(
                {
                    "ids": [str(uuid.uuid4())],
                    "embeddings": [embedding],
                    "metadatas": [{"type": "code_chunk"}],
                    "documents": ["some code snippet"],
                },
                vector_ctx,
            )

    start_time = time.perf_counter()
    total_requests = 200
    concurrent_requests = 10

    for i in range(0, total_requests, concurrent_requests):
        tasks = [mixed_op() for _ in range(min(concurrent_requests, total_requests - i))]
        await asyncio.gather(*tasks)

    duration = time.perf_counter() - start_time
    tps = total_requests / duration
    assert tps > 0
