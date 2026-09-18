from __future__ import annotations

import pytest

from smp.core.models import GraphNode, NodeType, SemanticProperties, StructuralProperties


@pytest.mark.asyncio
async def test_data_retention_purge_by_file(graph_store):
    """C-003: Verify that data can be purged via file-based deletion policy."""
    file_path = "src/obsolete.py"
    nodes = [
        GraphNode(
            id=f"n{i}",
            type=NodeType.FUNCTION,
            file_path=file_path,
            structural=StructuralProperties(
                name=f"f{i}", file=file_path, signature="", start_line=0, end_line=0, lines=0
            ),
            semantic=SemanticProperties(docstring="", status="enriched"),
        )
        for i in range(5)
    ]

    for n in nodes:
        await graph_store.upsert_node(n)

    assert await graph_store.count_nodes() == 5

    # Purge the file
    count = await graph_store.delete_nodes_by_file(file_path)
    assert count == 5
    assert await graph_store.count_nodes() == 0


@pytest.mark.asyncio
async def test_data_retention_nonexistent_file(graph_store):
    """Verify purge policy handles non-existent files gracefully."""
    count = await graph_store.delete_nodes_by_file("nonexistent.py")
    assert count == 0
