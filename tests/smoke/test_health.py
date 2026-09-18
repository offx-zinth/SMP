from __future__ import annotations

import pytest
from httpx import AsyncClient

from smp.protocol.server import create_app


@pytest.mark.asyncio
async def test_server_health():
    """S-001: Verify the server health endpoint returns 200 OK."""
    app = create_app()
    from httpx import ASGITransport

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        response = await ac.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_graph_store_health(graph_store):
    """S-002: Verify graph store can be connected and basic operations work."""
    assert graph_store is not None
    await graph_store.connect()
    report = await graph_store.integrity_report()
    assert report["ok"] is True


@pytest.mark.asyncio
async def test_vector_store_health(vector_store):
    """S-003: Verify vector store can be connected and basic operations work."""
    assert vector_store is not None
    await vector_store.connect()
    import numpy as np

    embedding = np.random.rand(128).astype(np.float32)
    await vector_store.upsert(
        ids=["health_check"], embeddings=[embedding.tolist()], metadatas=[{"text": "health"}], documents=["health"]
    )
    results = await vector_store.query(embedding, top_k=1)
    assert len(results) > 0
    assert results[0]["id"] == "health_check"
