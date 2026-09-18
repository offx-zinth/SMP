from __future__ import annotations

import numpy as np
import pytest

from smp.core.models import GraphNode, NodeType, SemanticProperties, StructuralProperties


class TestGraphVectorIntegration:
    """Integration tests for coordinated Graph and Vector store operations."""

    @pytest.mark.asyncio
    async def test_coordinated_upsert(self, graph_store, vector_store):
        """Test upserting a node and its corresponding vector embedding."""
        node = GraphNode(
            id="node_1",
            type=NodeType.FUNCTION,
            file_path="src/main.py",
            structural=StructuralProperties(name="main_func"),
            semantic=SemanticProperties(docstring="Main entry point"),
        )
        embedding = np.random.rand(128).astype(np.float32)

        await graph_store.upsert_node(node)
        await vector_store.upsert(ids=[node.id], embeddings=[embedding], metadatas=[{"text": node.semantic.docstring}])

        # Verify both stores have the data
        retrieved_node = await graph_store.get_node(node.id)
        assert retrieved_node == node

        # Verify vector store has the embedding (by querying it)
        results = await vector_store.query(embedding=embedding, top_k=1)
        assert len(results) > 0
        assert results[0]["id"] == node.id

    @pytest.mark.asyncio
    async def test_coordinated_delete(self, graph_store, vector_store):
        """Test deleting a node from both stores."""
        node_id = "node_del"
        node = GraphNode(id=node_id, type=NodeType.FUNCTION, file_path="src/main.py")
        embedding = np.random.rand(128).astype(np.float32)

        await graph_store.upsert_node(node)
        await vector_store.upsert(ids=[node_id], embeddings=[embedding], metadatas=[{}])

        await graph_store.delete_node(node_id)
        await vector_store.delete([node_id])

        assert await graph_store.get_node(node_id) is None
        results = await vector_store.query(embedding=embedding, top_k=1)
        assert not any(r["id"] == node_id for r in results)

    @pytest.mark.asyncio
    async def test_vector_to_graph_lookup(self, graph_store, vector_store):
        """Test finding a node via vector search and then retrieving it from the graph."""
        node = GraphNode(
            id="node_search",
            type=NodeType.FUNCTION,
            file_path="src/search.py",
            semantic=SemanticProperties(docstring="Search functionality"),
        )
        embedding = np.random.rand(128).astype(np.float32)

        await graph_store.upsert_node(node)
        await vector_store.upsert(ids=[node.id], embeddings=[embedding], metadatas=[{}])

        # Search in vector store
        results = await vector_store.query(embedding=embedding, top_k=1)
        found_id = results[0]["id"]

        # Retrieve from graph store
        retrieved_node = await graph_store.get_node(found_id)
        assert retrieved_node.id == "node_search"
        assert retrieved_node.file_path == "src/search.py"

    @pytest.mark.asyncio
    async def test_coordinated_update(self, graph_store, vector_store):
        """Test updating both graph properties and vector embeddings."""
        node_id = "node_upd"
        node = GraphNode(
            id=node_id,
            type=NodeType.FUNCTION,
            file_path="src/main.py",
            semantic=SemanticProperties(docstring="Old doc"),
        )
        embedding_old = np.random.rand(128).astype(np.float32)

        await graph_store.upsert_node(node)
        await vector_store.upsert(ids=[node_id], embeddings=[embedding_old], metadatas=[{"text": "Old doc"}])

        # Update
        new_node = GraphNode(
            id=node_id,
            type=NodeType.FUNCTION,
            file_path="src/main.py",
            semantic=SemanticProperties(docstring="New doc"),
        )
        embedding_new = np.random.rand(128).astype(np.float32)

        await graph_store.upsert_node(new_node)
        await vector_store.upsert(ids=[node_id], embeddings=[embedding_new], metadatas=[{"text": "New doc"}])

        assert (await graph_store.get_node(node_id)).semantic.docstring == "New doc"
        results = await vector_store.query(embedding=embedding_new, top_k=1)
        assert results[0]["id"] == node_id

    @pytest.mark.asyncio
    async def test_batch_coordinated_upsert(self, graph_store, vector_store):
        """Test batch upserting nodes and embeddings."""
        nodes = [GraphNode(id=f"bn_{i}", type=NodeType.FUNCTION, file_path=f"f{i}.py") for i in range(10)]
        embeddings = [np.random.rand(128).astype(np.float32) for _ in range(10)]

        for node, emb in zip(nodes, embeddings, strict=False):
            await graph_store.upsert_node(node)
            await vector_store.upsert(ids=[node.id], embeddings=[emb], metadatas=[{}])

        for i in range(10):
            assert await graph_store.get_node(f"bn_{i}") is not None
            res = await vector_store.query(embedding=embeddings[i], top_k=1)
            assert res[0]["id"] == f"bn_{i}"

    @pytest.mark.asyncio
    async def test_vector_query_filtering_with_graph_types(self, graph_store, vector_store):
        """Test filtering vector search based on node types from the graph store."""
        # Create one FUNCTION and one CLASS
        node_func = GraphNode(id="f1", type=NodeType.FUNCTION, file_path="f.py")
        node_class = GraphNode(id="c1", type=NodeType.CLASS, file_path="c.py")

        await graph_store.upsert_node(node_func)
        await graph_store.upsert_node(node_class)

        emb_func = np.random.rand(128).astype(np.float32)
        emb_class = np.random.rand(128).astype(np.float32)

        await vector_store.upsert(ids=["f1"], embeddings=[emb_func], metadatas=[{"type": "Function"}])
        await vector_store.upsert(ids=["c1"], embeddings=[emb_class], metadatas=[{"type": "Class"}])

        # Search and check if we can filter by metadata in vector store that mirrors graph type
        res = await vector_store.query(embedding=emb_func, top_k=1, where={"type": "Function"})
        assert res[0]["id"] == "f1"

        res = await vector_store.query(embedding=emb_func, top_k=1, where={"type": "Class"})
        assert not any(r["id"] == "f1" for r in res)

    @pytest.mark.asyncio
    async def test_graph_traversal_with_vector_enrichment(self, graph_store, vector_store):
        """Test traversing the graph and fetching semantic details from vector store."""
        # A calls B
        node_a = GraphNode(id="A", type=NodeType.FUNCTION, file_path="a.py")
        node_b = GraphNode(id="B", type=NodeType.FUNCTION, file_path="b.py")
        from smp.core.models import EdgeType, GraphEdge

        edge = GraphEdge(source_id="A", target_id="B", type=EdgeType.CALLS)

        await graph_store.upsert_node(node_a)
        await graph_store.upsert_node(node_b)
        await graph_store.upsert_edge(edge)

        emb_b = np.random.rand(128).astype(np.float32)
        await vector_store.upsert(ids=["B"], embeddings=[emb_b], metadatas=[{"text": "B is a helper"}])

        # Traverse from A
        neighbors = await graph_store.traverse("A", relationship=EdgeType.CALLS)
        assert any(n.id == "B" for n in neighbors)

        # Enrich neighbor B with vector data
        res = await vector_store.query(embedding=emb_b, top_k=1)
        assert res[0]["id"] == "B"
        assert res[0]["metadata"]["text"] == "B is a helper"

    @pytest.mark.asyncio
    async def test_mismatched_stores_handling(self, graph_store, vector_store):
        """Test behavior when a node exists in graph but not in vector store."""
        node = GraphNode(id="ghost", type=NodeType.FUNCTION, file_path="g.py")
        await graph_store.upsert_node(node)

        # No vector upsert

        # Query vector store for it (should not find it)
        emb = np.random.rand(128).astype(np.float32)
        res = await vector_store.query(embedding=emb, top_k=1)
        assert not any(r["id"] == "ghost" for r in res)

    @pytest.mark.asyncio
    async def test_vector_store_id_consistency(self, graph_store, vector_store):
        """Ensure vector store IDs strictly follow graph store node IDs."""
        node_id = "consistency_test"
        node = GraphNode(id=node_id, type=NodeType.FUNCTION, file_path="c.py")
        await graph_store.upsert_node(node)

        emb = np.random.rand(128).astype(np.float32)
        await vector_store.upsert(ids=[node_id], embeddings=[emb], metadatas=[{}])

        res = await vector_store.query(embedding=emb, top_k=1)
        assert res[0]["id"] == node_id

    @pytest.mark.asyncio
    async def test_large_batch_coordinated_sync(self, graph_store, vector_store):
        """Test syncing 100 nodes across both stores."""
        for i in range(100):
            nid = f"node_{i}"
            await graph_store.upsert_node(GraphNode(id=nid, type=NodeType.FUNCTION, file_path=f"f{i}.py"))
            await vector_store.upsert(ids=[nid], embeddings=[np.random.rand(128).astype(np.float32)], metadatas=[{}])

        # Verify random sample
        import random

        sample_id = f"node_{random.randint(0, 99)}"
        assert await graph_store.get_node(sample_id) is not None
        res = await vector_store.query(embedding=np.random.rand(128).astype(np.float32), top_k=100)
        assert any(r["id"] == sample_id for r in res)

    @pytest.mark.asyncio
    async def test_coordinated_upsert_with_metadata(self, graph_store, vector_store):
        """Test upserting nodes with rich metadata in both stores."""
        node = GraphNode(
            id="meta_1", type=NodeType.FUNCTION, file_path="m.py", semantic=SemanticProperties(tags=["api", "auth"])
        )
        await graph_store.upsert_node(node)
        await vector_store.upsert(
            ids=[node.id], embeddings=[np.random.rand(128).astype(np.float32)], metadatas=[{"tags": ["api", "auth"]}]
        )

        # Verify graph tags
        retrieved = await graph_store.get_node("meta_1")
        assert "api" in retrieved.semantic.tags

        # Verify vector tags
        res = await vector_store.query(embedding=np.random.rand(128).astype(np.float32), top_k=100)
        # Search for meta_1 specifically if possible, or just check metadata of the one we found
        for r in res:
            if r["id"] == "meta_1":
                assert "api" in r["metadata"]["tags"]

    @pytest.mark.asyncio
    async def test_coordinated_delete_batch(self, graph_store, vector_store):
        """Test batch deletion across both stores."""
        ids = [f"del_{i}" for i in range(10)]
        for nid in ids:
            await graph_store.upsert_node(GraphNode(id=nid, type=NodeType.FUNCTION, file_path="d.py"))
            await vector_store.upsert(ids=[nid], embeddings=[np.random.rand(128).astype(np.float32)], metadatas=[{}])

        for nid in ids:
            await graph_store.delete_node(nid)
            await vector_store.delete([nid])

        for nid in ids:
            assert await graph_store.get_node(nid) is None
            res = await vector_store.query(embedding=np.random.rand(128).astype(np.float32), top_k=100)
            assert not any(r["id"] == nid for r in res)

    @pytest.mark.asyncio
    async def test_semantic_update_triggering_vector_update(self, graph_store, vector_store):
        """Test updating semantic properties in graph and corresponding vector embedding."""
        node_id = "semantic_upd"
        node = GraphNode(
            id=node_id, type=NodeType.FUNCTION, file_path="s.py", semantic=SemanticProperties(docstring="Old")
        )
        emb_old = np.random.rand(128).astype(np.float32)

        await graph_store.upsert_node(node)
        await vector_store.upsert(ids=[node_id], embeddings=[emb_old], metadatas=[{"text": "Old"}])

        # Update
        node.semantic.docstring = "New"
        emb_new = np.random.rand(128).astype(np.float32)
        await graph_store.upsert_node(node)
        await vector_store.upsert(ids=[node_id], embeddings=[emb_new], metadatas=[{"text": "New"}])

        assert (await graph_store.get_node(node_id)).semantic.docstring == "New"
        res = await vector_store.query(embedding=emb_new, top_k=1)
        assert res[0]["id"] == node_id
        assert res[0]["metadata"]["text"] == "New"

    @pytest.mark.asyncio
    async def test_vector_search_relevance_to_graph_structure(self, graph_store, vector_store):
        """Test that vector search results can be ranked/filtered by graph distance."""
        # A -> B -> C
        node_a = GraphNode(id="A", type=NodeType.FUNCTION, file_path="a.py")
        node_b = GraphNode(id="B", type=NodeType.FUNCTION, file_path="b.py")
        node_c = GraphNode(id="C", type=NodeType.FUNCTION, file_path="c.py")
        from smp.core.models import EdgeType, GraphEdge

        await graph_store.upsert_node(node_a)
        await graph_store.upsert_node(node_b)
        await graph_store.upsert_node(node_c)
        await graph_store.upsert_edge(GraphEdge("A", "B", EdgeType.CALLS))
        await graph_store.upsert_edge(GraphEdge("B", "C", EdgeType.CALLS))

        emb_a = np.random.rand(128).astype(np.float32)
        emb_b = np.random.rand(128).astype(np.float32)
        emb_c = np.random.rand(128).astype(np.float32)

        await vector_store.upsert(ids=["A"], embeddings=[emb_a], metadatas=[{}])
        await vector_store.upsert(ids=["B"], embeddings=[emb_b], metadatas=[{}])
        await vector_store.upsert(ids=["C"], embeddings=[emb_c], metadatas=[{}])

        # Search for something similar to A
        res = await vector_store.query(embedding=emb_a, top_k=3)
        # In a real scenario, we'd check if A's neighbors (B) are also high rank or used to boost rank
        # Here we just verify we can find them
        ids = [r["id"] for r in res]
        assert "A" in ids
        assert "B" in ids or "C" in ids

    @pytest.mark.asyncio
    async def test_graph_node_fingerprint_vector_sync(self, graph_store, vector_store):
        """Test using GraphNode fingerprint as vector store ID."""
        node = GraphNode(
            id="node_1",
            type=NodeType.FUNCTION,
            file_path="src/main.py",
            structural=StructuralProperties(name="main", start_line=1),
        )
        fp = node.fingerprint()

        await graph_store.upsert_node(node)
        await vector_store.upsert(ids=[fp], embeddings=[np.random.rand(128).astype(np.float32)], metadatas=[{}])

        res = await vector_store.query(embedding=np.random.rand(128).astype(np.float32), top_k=100)
        assert any(r["id"] == fp for r in res)

    @pytest.mark.asyncio
    async def test_vector_store_empty_query(self, graph_store, vector_store):
        """Test querying the vector store when no nodes are indexed."""
        emb = np.random.rand(128).astype(np.float32)
        res = await vector_store.query(embedding=emb, top_k=5)
        assert res == []

    @pytest.mark.asyncio
    async def test_graph_store_empty_lookup(self, graph_store, vector_store):
        """Test looking up a node in graph store that only exists in vector store."""
        emb = np.random.rand(128).astype(np.float32)
        await vector_store.upsert(ids=["vector_only"], embeddings=[emb], metadatas=[{}])

        assert await graph_store.get_node("vector_only") is None

    @pytest.mark.asyncio
    async def test_coordinated_upsert_different_types(self, graph_store, vector_store):
        """Test coordinated upsert for different NodeType values."""
        types = [NodeType.CLASS, NodeType.FUNCTION, NodeType.VARIABLE, NodeType.FILE]
        for i, t in enumerate(types):
            nid = f"type_{i}"
            await graph_store.upsert_node(GraphNode(id=nid, type=t, file_path="t.py"))
            await vector_store.upsert(ids=[nid], embeddings=[np.random.rand(128).astype(np.float32)], metadatas=[{}])

        for i, t in enumerate(types):
            nid = f"type_{i}"
            node = await graph_store.get_node(nid)
            assert node.type == t
            res = await vector_store.query(embedding=np.random.rand(128).astype(np.float32), top_k=100)
            assert any(r["id"] == nid for r in res)

    @pytest.mark.asyncio
    async def test_vector_search_with_graph_context(self, graph_store, vector_store):
        """Test vector search using context derived from graph traversal."""
        # A -> B, A -> C
        node_a = GraphNode(id="A", type=NodeType.FUNCTION, file_path="a.py")
        node_b = GraphNode(id="B", type=NodeType.FUNCTION, file_path="b.py")
        node_c = GraphNode(id="C", type=NodeType.FUNCTION, file_path="c.py")
        from smp.core.models import EdgeType, GraphEdge

        await graph_store.upsert_node(node_a)
        await graph_store.upsert_node(node_b)
        await graph_store.upsert_node(node_c)
        await graph_store.upsert_edge(GraphEdge("A", "B", EdgeType.CALLS))
        await graph_store.upsert_edge(GraphEdge("A", "C", EdgeType.CALLS))

        emb_b = np.random.rand(128).astype(np.float32)
        emb_c = np.random.rand(128).astype(np.float32)
        await vector_store.upsert(ids=["B"], embeddings=[emb_b], metadatas=[{}])
        await vector_store.upsert(ids=["C"], embeddings=[emb_c], metadatas=[{}])

        # Get neighbors of A
        neighbors = await graph_store.traverse("A", relationship=EdgeType.CALLS)
        assert any(n.id == "B" for n in neighbors) and any(n.id == "C" for n in neighbors)

        # Use a neighbor's embedding to find other similar nodes
        res = await vector_store.query(embedding=emb_b, top_k=2)
        assert any(r["id"] in [n.id for n in neighbors] for r in res)

    @pytest.mark.asyncio
    async def test_coordinated_upsert_large_metadata(self, graph_store, vector_store):
        """Test coordinating stores with large metadata documents."""
        node = GraphNode(id="large_meta", type=NodeType.FUNCTION, file_path="l.py")
        large_doc = "word " * 1000
        await graph_store.upsert_node(node)
        await vector_store.upsert(
            ids=[node.id], embeddings=[np.random.rand(128).astype(np.float32)], metadatas=[{"text": large_doc}]
        )

        res = await vector_store.query(embedding=np.random.rand(128).astype(np.float32), top_k=100)
        for r in res:
            if r["id"] == "large_meta":
                assert r["metadata"]["text"] == large_doc

    @pytest.mark.asyncio
    async def test_coordinated_delete_unexisting(self, graph_store, vector_store):
        """Test coordinated deletion of nodes that don't exist."""
        # Should not raise exception
        await graph_store.delete_node("none")
        await vector_store.delete(["none"])

    @pytest.mark.asyncio
    async def test_vector_store_dimension_consistency(self, graph_store, vector_store):
        """Ensure vector store dimensions match the expected 128."""
        emb = np.random.rand(128).astype(np.float32)
        await vector_store.upsert(ids=["dim_test"], embeddings=[emb], metadatas=[{}])

        res = await vector_store.query(embedding=emb, top_k=1)
        assert res[0]["id"] == "dim_test"

        # Attempting to upsert with wrong dimension should (ideally) fail or be handled
        # Depending on implementation of MMapVectorStore, this might raise an error.
        with pytest.raises(ValueError):
            wrong_emb = np.random.rand(64).astype(np.float32)
            await vector_store.upsert(ids=["wrong_dim"], embeddings=[wrong_emb], metadatas=[{}])

    @pytest.mark.asyncio
    async def test_coordinated_upsert_performance_baseline(self, graph_store, vector_store):
        """Baseline test for coordinated upsert latency."""
        import time

        start = time.perf_counter()
        for i in range(50):
            nid = f"perf_{i}"
            await graph_store.upsert_node(GraphNode(id=nid, type=NodeType.FUNCTION, file_path="p.py"))
            await vector_store.upsert(ids=[nid], embeddings=[np.random.rand(128).astype(np.float32)], metadatas=[{}])
        end = time.perf_counter()
        assert (end - start) < 5.0  # Loose bound for integration test

    @pytest.mark.asyncio
    async def test_vector_search_with_graph_node_existence_check(self, graph_store, vector_store):
        """Test that vector search results are validated against graph store existence."""
        # Put something in vector store but NOT in graph store
        await vector_store.upsert(
            ids=["vector_only"], embeddings=[np.random.rand(128).astype(np.float32)], metadatas=[{}]
        )

        # Put something in both
        node = GraphNode(id="both", type=NodeType.FUNCTION, file_path="b.py")
        await graph_store.upsert_node(node)
        await vector_store.upsert(ids=["both"], embeddings=[np.random.rand(128).astype(np.float32)], metadatas=[{}])

        # Query vector store
        res = await vector_store.query(embedding=np.random.rand(128).astype(np.float32), top_k=100)

        # Filter results by those that also exist in graph store
        valid_results = []
        for r in res:
            if await graph_store.get_node(r["id"]) is not None:
                valid_results.append(r)

        assert any(r["id"] == "both" for r in valid_results)
        assert not any(r["id"] == "vector_only" for r in valid_results)

    @pytest.mark.asyncio
    async def test_sync_consistency_after_reconnect(self, graph_store, vector_store):
        """Test that data remains consistent after reconnecting to stores."""
        node_id = "reconnect_test"
        node = GraphNode(id=node_id, type=NodeType.FUNCTION, file_path="r.py")
        embedding = np.random.rand(128).astype(np.float32)

        await graph_store.upsert_node(node)
        await vector_store.upsert(ids=[node_id], embeddings=[embedding], metadatas=[{}])

        await graph_store.disconnect()
        await vector_store.close()

        await graph_store.connect()
        await vector_store.connect()

        retrieved_node = await graph_store.get_node(node_id)
        assert retrieved_node is not None
        assert retrieved_node.id == node_id

        results = await vector_store.query(embedding=embedding, top_k=1)
        assert results[0]["id"] == node_id
