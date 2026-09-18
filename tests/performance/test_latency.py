from __future__ import annotations

import random
import uuid

import pytest

from smp.engine.query import DefaultQueryEngine
from smp.protocol.handlers import memory, query, vector


@pytest.mark.asyncio
async def test_p001_navigate_latency(benchmark, populated_graph_store):
    """P-001: Measure latency of smp/navigate."""
    engine = DefaultQueryEngine(graph_store=populated_graph_store)
    ctx = {"engine": engine}
    params = {"query": "class User", "include_relationships": True}

    async def run() -> None:
        await query.navigate(params, ctx)

    await benchmark(run)


@pytest.mark.asyncio
async def test_p002_search_latency(benchmark, populated_graph_store):
    """P-002: Measure latency of smp/search."""
    engine = DefaultQueryEngine(graph_store=populated_graph_store)
    ctx = {"engine": engine}
    params = {"query": "auth", "match": "any", "filter": {}, "top_k": 10}

    async def run() -> None:
        await query.search(params, ctx)

    await benchmark(run)


@pytest.mark.asyncio
async def test_p003_context_latency(benchmark, populated_graph_store):
    """P-003: Measure latency of smp/context."""
    engine = DefaultQueryEngine(graph_store=populated_graph_store)
    ctx = {"engine": engine}
    params = {"file_path": "src/auth/login.py", "scope": "function", "depth": 2}

    async def run() -> None:
        await query.context(params, ctx)

    await benchmark(run)


@pytest.mark.asyncio
async def test_p004_trace_latency(benchmark, populated_graph_store):
    """P-004: Measure latency of smp/trace."""
    engine = DefaultQueryEngine(graph_store=populated_graph_store)
    ctx = {"engine": engine}
    params = {"start": "func_login", "relationship": "calls", "depth": 3, "direction": "out"}

    async def run() -> None:
        await query.trace(params, ctx)

    await benchmark(run)


@pytest.mark.asyncio
async def test_p005_update_latency(benchmark, populated_graph_store):
    """P-005: Measure latency of smp/update."""
    ctx = {"graph": populated_graph_store}
    params = {"file_path": "src/auth/login.py"}

    async def run() -> None:
        await memory.update(params, ctx)

    await benchmark(run)


@pytest.mark.asyncio
async def test_p006_vector_search_latency(benchmark, populated_vector_store):
    """P-006: Measure latency of smp/vector/search."""
    ctx = {"vector_store": populated_vector_store}
    embedding = [random.uniform(-1, 1) for _ in range(128)]
    params = {"embedding": embedding, "top_k": 5, "where": {}}

    async def run() -> None:
        await vector.vector_search(params, ctx)

    await benchmark(run)


@pytest.mark.asyncio
async def test_p007_vector_upsert_latency(benchmark, populated_vector_store):
    """P-007: Measure latency of smp/vector/upsert."""
    ctx = {"vector_store": populated_vector_store}
    embedding = [random.uniform(-1, 1) for _ in range(128)]
    params = {
        "ids": [str(uuid.uuid4())],
        "embeddings": [embedding],
        "metadatas": [{"type": "code_chunk"}],
        "documents": ["some code snippet"],
    }

    async def run() -> None:
        await vector.vector_upsert(params, ctx)

    await benchmark(run)


@pytest.mark.asyncio
async def test_p008_batch_update_latency(benchmark, populated_graph_store):
    """P-008: Measure latency of smp/batch_update."""
    ctx = {"graph": populated_graph_store}
    params = {
        "changes": [
            {"file_path": "src/auth/login.py"},
            {"file_path": "src/auth/session.py"},
            {"file_path": "src/db/models.py"},
        ]
    }

    async def run() -> None:
        await memory.batch_update(params, ctx)

    await benchmark(run)
