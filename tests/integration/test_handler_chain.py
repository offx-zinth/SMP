from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from smp.core.models import GraphNode, NodeType, SemanticProperties
from smp.engine.query import DefaultQueryEngine
from smp.protocol.handlers import enrichment as enrichment_handlers
from smp.protocol.handlers import query as query_handlers


class TestHandlerChainIntegration:
    """Integration tests for chains of handler operations: Query -> Enrich -> Update."""

    @pytest.fixture
    def chain_ctx(self, graph_store):
        """Provide a context with both engine and graph for handler chains."""
        engine = DefaultQueryEngine(graph_store=graph_store)
        return {"engine": engine, "graph": graph_store, "principal": "test_user", "correlation_id": "test_corr_id"}

    @pytest.mark.asyncio
    async def test_search_then_enrich(self, chain_ctx, graph_store):
        """Test: search for a node, then enrich it."""
        # Setup
        node = GraphNode(
            id="target_1",
            type=NodeType.FUNCTION,
            file_path="src/main.py",
            semantic=SemanticProperties(status="no_metadata"),
        )
        await graph_store.upsert_node(node)

        # 1. Search
        search_res = await query_handlers.search({"query": "target_1", "top_k": 5}, chain_ctx)
        matches = search_res.get("matches", [])
        assert any(m.get("id") == "target_1" for m in matches)

        node_id = "target_1"  # fallback if search return is different

        # 2. Enrich
        enrich_res = await enrichment_handlers.enrich({"node_id": node_id}, chain_ctx)
        assert enrich_res["enriched"] is True

        # Verify
        updated_node = await graph_store.get_node(node_id)
        assert updated_node.semantic.status == "enriched"

    @pytest.mark.asyncio
    async def test_search_then_annotate(self, chain_ctx, graph_store):
        """Test: search for a node, then annotate it."""
        node_id = "target_ann"
        await graph_store.upsert_node(GraphNode(id=node_id, type=NodeType.FUNCTION, file_path="src/main.py"))

        # 1. Search (simulated)
        # 2. Annotate
        ann_res = await enrichment_handlers.annotate(
            {"node_id": node_id, "description": "Important function", "tags": ["critical"]}, chain_ctx
        )
        assert ann_res["annotated"] is True

        # Verify
        updated_node = await graph_store.get_node(node_id)
        assert updated_node.semantic.description == "Important function"
        assert "critical" in updated_node.semantic.tags
        assert updated_node.semantic.manually_set is True

    @pytest.mark.asyncio
    async def test_search_then_enrich_batch(self, chain_ctx, graph_store):
        """Test: search (simulated) -> enrich batch by scope."""
        # Setup multiple nodes in a scope
        for i in range(5):
            await graph_store.upsert_node(
                GraphNode(id=f"n_{i}", type=NodeType.FUNCTION, file_path=f"src/scope1/f{i}.py")
            )

        # Enrich batch
        res = await enrichment_handlers.enrich_batch({"scope": "src/scope1", "force": False}, chain_ctx)
        assert res["enriched"] == 5

        # Verify
        node = await graph_store.get_node("n_0")
        assert node.semantic.status == "enriched"

    @pytest.mark.asyncio
    async def test_search_then_annotate_bulk(self, chain_ctx, graph_store):
        """Test: search (simulated) -> annotate bulk."""
        ids = ["b1", "b2", "b3"]
        for nid in ids:
            await graph_store.upsert_node(GraphNode(id=nid, type=NodeType.FUNCTION, file_path="src/main.py"))

        res = await enrichment_handlers.annotate_bulk(
            {
                "annotations": [
                    {"node_id": "b1", "description": "d1", "tags": ["t1"]},
                    {"node_id": "b2", "description": "d2", "tags": ["t2"]},
                    {"node_id": "b3", "description": "d3", "tags": ["t3"]},
                ]
            },
            chain_ctx,
        )
        assert res["annotated"] == 3

        # Verify
        node = await graph_store.get_node("b2")
        assert node.semantic.description == "d2"
        assert "t2" in node.semantic.tags

    @pytest.mark.asyncio
    async def test_search_then_tag_scope(self, chain_ctx, graph_store):
        """Test: search (simulated) -> tag by scope."""
        for i in range(5):
            await graph_store.upsert_node(
                GraphNode(id=f"t_{i}", type=NodeType.FUNCTION, file_path=f"src/scope_tag/f{i}.py")
            )

        res = await enrichment_handlers.tag({"scope": "src/scope_tag", "tags": ["shared"], "action": "add"}, chain_ctx)
        assert res["updated"] == 5

        # Verify
        node = await graph_store.get_node("t_0")
        assert "shared" in node.semantic.tags

    @pytest.mark.asyncio
    async def test_chain_enrich_then_annotate(self, chain_ctx, graph_store):
        """Test Chain: search -> enrich -> annotate."""
        node_id = "chain_1"
        await graph_store.upsert_node(GraphNode(id=node_id, type=NodeType.FUNCTION, file_path="src/main.py"))

        # 1. Enrich
        await enrichment_handlers.enrich({"node_id": node_id}, chain_ctx)
        # 2. Annotate
        await enrichment_handlers.annotate({"node_id": node_id, "description": "desc", "tags": ["tag"]}, chain_ctx)

        node = await graph_store.get_node(node_id)
        assert node.semantic.status == "enriched"
        assert node.semantic.description == "desc"
        assert "tag" in node.semantic.tags

    @pytest.mark.asyncio
    async def test_chain_annotate_then_enrich_skips(self, chain_ctx, graph_store):
        """Test Chain: annotate -> enrich (manual nodes are protected)."""
        node_id = "chain_skip"
        await graph_store.upsert_node(GraphNode(id=node_id, type=NodeType.FUNCTION, file_path="src/main.py"))

        # 1. Annotate (marks manually_set=True)
        await enrichment_handlers.annotate({"node_id": node_id, "description": "desc"}, chain_ctx)

        # 2. Enrich without force must skip manually_set nodes.
        res = await enrichment_handlers.enrich({"node_id": node_id, "force": False}, chain_ctx)
        assert res.get("skipped") is True

        # 3. Enrich with force overwrites.
        res2 = await enrichment_handlers.enrich({"node_id": node_id, "force": True}, chain_ctx)
        assert res2["enriched"] is True

    @pytest.mark.asyncio
    async def test_chain_enrich_then_tag_remove(self, chain_ctx, graph_store):
        """Test Chain: enrich -> tag (remove)."""
        node_id = "tag_rem"
        node = GraphNode(
            id=node_id,
            type=NodeType.FUNCTION,
            file_path="src/main.py",
            semantic=SemanticProperties(tags=["old", "keep"]),
        )
        await graph_store.upsert_node(node)

        # 1. Enrich
        await enrichment_handlers.enrich({"node_id": node_id}, chain_ctx)
        # 2. Tag remove
        await enrichment_handlers.tag({"scope": "src/main.py", "tags": ["old"], "action": "remove"}, chain_ctx)

        node = await graph_store.get_node(node_id)
        assert "old" not in node.semantic.tags
        assert "keep" in node.semantic.tags
        assert node.semantic.status == "enriched"

    @pytest.mark.asyncio
    async def test_chain_search_enrich_stale(self, chain_ctx, graph_store):
        """Test Chain: search -> enrich_stale."""
        node_id = "stale_1"
        node = GraphNode(
            id=node_id, type=NodeType.FUNCTION, file_path="src/main.py", semantic=SemanticProperties(status="stale")
        )
        await graph_store.upsert_node(node)

        res = await enrichment_handlers.enrich_stale({"scope": "src/main.py"}, chain_ctx)
        assert res["enriched"] == 1

        node = await graph_store.get_node(node_id)
        assert node.semantic.status == "enriched"

    @pytest.mark.asyncio
    async def test_chain_search_enrich_status(self, chain_ctx, graph_store):
        """Test Chain: search -> enrich_status."""
        await graph_store.upsert_node(
            GraphNode(
                id="n1", type=NodeType.FUNCTION, file_path="f1.py", semantic=SemanticProperties(status="enriched")
            )
        )
        await graph_store.upsert_node(
            GraphNode(id="n2", type=NodeType.FUNCTION, file_path="f2.py", semantic=SemanticProperties(status="stale"))
        )
        await graph_store.upsert_node(
            GraphNode(
                id="n3", type=NodeType.FUNCTION, file_path="f3.py", semantic=SemanticProperties(status="no_metadata")
            )
        )

        res = await enrichment_handlers.enrich_status({"scope": "full"}, chain_ctx)
        assert res["by_status"]["enriched"] == 1
        assert res["by_status"]["stale"] == 1
        assert res["by_status"]["no_metadata"] == 1

    @pytest.mark.asyncio
    async def test_chain_annotate_bulk_missing_nodes(self, chain_ctx, graph_store):
        """Test: annotate_bulk with some missing nodes."""
        await graph_store.upsert_node(GraphNode(id="exists", type=NodeType.FUNCTION, file_path="f.py"))

        res = await enrichment_handlers.annotate_bulk(
            {
                "annotations": [
                    {"node_id": "exists", "description": "d1"},
                    {"node_id": "missing", "description": "d2"},
                ]
            },
            chain_ctx,
        )
        assert res["annotated"] == 1
        assert "missing" in res["missing"]

    @pytest.mark.asyncio
    async def test_chain_tag_set_action(self, chain_ctx, graph_store):
        """Test Chain: search -> tag (set)."""
        node_id = "tag_set"
        node = GraphNode(
            id=node_id, type=NodeType.FUNCTION, file_path="src/main.py", semantic=SemanticProperties(tags=["t1", "t2"])
        )
        await graph_store.upsert_node(node)

        await enrichment_handlers.tag({"scope": "src/main.py", "tags": ["new1", "new2"], "action": "set"}, chain_ctx)

        node = await graph_store.get_node(node_id)
        assert node.semantic.tags == ["new1", "new2"]

    @pytest.mark.asyncio
    async def test_chain_enrich_force_update(self, chain_ctx, graph_store):
        """Test Chain: enrich -> enrich (force)."""
        node_id = "force_enrich"
        await graph_store.upsert_node(
            GraphNode(
                id=node_id, type=NodeType.FUNCTION, file_path="f.py", semantic=SemanticProperties(status="enriched")
            )
        )

        res = await enrichment_handlers.enrich({"node_id": node_id, "force": True}, chain_ctx)
        assert res["enriched"] is True

        # Verify enriched_at was updated (roughly)
        node = await graph_store.get_node(node_id)
        assert node.semantic.enriched_at is not None

    @pytest.mark.asyncio
    async def test_chain_annotate_force_override(self, chain_ctx, graph_store):
        """Test Chain: annotate -> annotate (force override)."""
        node_id = "force_ann"
        await graph_store.upsert_node(
            GraphNode(
                id=node_id,
                type=NodeType.FUNCTION,
                file_path="f.py",
                semantic=SemanticProperties(description="old", manually_set=True),
            )
        )

        res = await enrichment_handlers.annotate({"node_id": node_id, "description": "new", "force": True}, chain_ctx)
        assert res["annotated"] is True

        node = await graph_store.get_node(node_id)
        assert node.semantic.description == "new"

    @pytest.mark.asyncio
    async def test_chain_tag_invalid_action(self, chain_ctx, graph_store):
        """Test: tag with invalid action."""
        await graph_store.upsert_node(GraphNode(id="n1", type=NodeType.FUNCTION, file_path="f.py"))
        res = await enrichment_handlers.tag({"scope": "f.py", "tags": ["t"], "action": "invalid"}, chain_ctx)
        assert res["updated"] == 0

    @pytest.mark.asyncio
    async def test_chain_complex_lifecycle(self, chain_ctx, graph_store):
        """Test a complex lifecycle: Ingest (sim) -> Search -> Enrich -> Annotate -> Tag -> Enrich Stale."""
        node_id = "lifecycle_1"
        await graph_store.upsert_node(
            GraphNode(
                id=node_id,
                type=NodeType.FUNCTION,
                file_path="src/lifecycle.py",
                semantic=SemanticProperties(status="no_metadata"),
            )
        )

        # 1. Enrich
        await enrichment_handlers.enrich({"node_id": node_id}, chain_ctx)
        # 2. Annotate
        await enrichment_handlers.annotate(
            {"node_id": node_id, "description": "Lifecycle node", "tags": ["L1"]}, chain_ctx
        )
        # 3. Tag add
        await enrichment_handlers.tag({"scope": "src/lifecycle.py", "tags": ["L2"], "action": "add"}, chain_ctx)
        # 4. Mark as stale manually
        node = await graph_store.get_node(node_id)
        node.semantic.status = "stale"
        await graph_store.upsert_node(node)
        # 5. Enrich stale
        await enrichment_handlers.enrich_stale({"scope": "src/lifecycle.py"}, chain_ctx)

        final_node = await graph_store.get_node(node_id)
        assert final_node.semantic.status == "enriched"
        assert final_node.semantic.description == "Lifecycle node"
        assert "L1" in final_node.semantic.tags
        assert "L2" in final_node.semantic.tags

    @pytest.mark.asyncio
    async def test_chain_enrich_batch_force(self, chain_ctx, graph_store):
        """Test: enrich_batch with force=True."""
        for i in range(3):
            await graph_store.upsert_node(
                GraphNode(
                    id=f"f_{i}",
                    type=NodeType.FUNCTION,
                    file_path="f.py",
                    semantic=SemanticProperties(status="enriched"),
                )
            )

        res = await enrichment_handlers.enrich_batch({"scope": "f.py", "force": True}, chain_ctx)
        assert res["enriched"] == 3
        assert res["skipped"] == 0

    @pytest.mark.asyncio
    async def test_chain_annotate_bulk_mixed_status(self, chain_ctx, graph_store):
        """Test: annotate_bulk on nodes with different existing statuses."""
        await graph_store.upsert_node(
            GraphNode(id="n1", type=NodeType.FUNCTION, file_path="f.py", semantic=SemanticProperties(manually_set=True))
        )
        await graph_store.upsert_node(
            GraphNode(
                id="n2", type=NodeType.FUNCTION, file_path="f.py", semantic=SemanticProperties(manually_set=False)
            )
        )

        # annotate_bulk does NOT check manually_set in the current implementation (see enrichment.py:149)
        # It just upserts. Let's verify this behavior.
        res = await enrichment_handlers.annotate_bulk(
            {
                "annotations": [
                    {"node_id": "n1", "description": "d1"},
                    {"node_id": "n2", "description": "d2"},
                ]
            },
            chain_ctx,
        )
        assert res["annotated"] == 2

        node1 = await graph_store.get_node("n1")
        assert node1.semantic.description == "d1"

    @pytest.mark.asyncio
    async def test_chain_tag_remove_nonexistent_tag(self, chain_ctx, graph_store):
        """Test: tag remove for a tag that doesn't exist."""
        node_id = "tag_none"
        await graph_store.upsert_node(
            GraphNode(id=node_id, type=NodeType.FUNCTION, file_path="f.py", semantic=SemanticProperties(tags=["t1"]))
        )

        res = await enrichment_handlers.tag({"scope": "f.py", "tags": ["t2"], "action": "remove"}, chain_ctx)
        assert res["updated"] == 0  # No change

        node = await graph_store.get_node(node_id)
        assert node.semantic.tags == ["t1"]

    @pytest.mark.asyncio
    async def test_chain_enrich_status_empty_scope(self, chain_ctx, graph_store):
        """Test: enrich_status on scope with no nodes."""
        res = await enrichment_handlers.enrich_status({"scope": "empty_dir"}, chain_ctx)
        assert res["total"] == 0
        assert res["by_status"] == {}

    @pytest.mark.asyncio
    async def test_chain_annotate_missing_node(self, chain_ctx, graph_store):
        """Test: annotate a node that doesn't exist."""
        res = await enrichment_handlers.annotate({"node_id": "ghost", "description": "desc"}, chain_ctx)
        assert res["annotated"] is False
        assert res["error"] == "node_not_found"

    @pytest.mark.asyncio
    async def test_chain_enrich_missing_node(self, chain_ctx, graph_store):
        """Test: enrich a node that doesn't exist."""
        res = await enrichment_handlers.enrich({"node_id": "ghost"}, chain_ctx)
        assert res["enriched"] is False
        assert res["error"] == "node_not_found"

    @pytest.mark.asyncio
    async def test_chain_tag_empty_tags(self, chain_ctx, graph_store):
        """Test: tag with empty tags list."""
        await graph_store.upsert_node(
            GraphNode(id="n1", type=NodeType.FUNCTION, file_path="f.py", semantic=SemanticProperties(tags=["t1"]))
        )
        res = await enrichment_handlers.tag({"scope": "f.py", "tags": [], "action": "add"}, chain_ctx)
        assert res["updated"] == 0

        node = await graph_store.get_node("n1")
        assert node.semantic.tags == ["t1"]

    @pytest.mark.asyncio
    async def test_chain_enrich_batch_full_scope(self, chain_ctx, graph_store):
        """Test: enrich_batch with scope='full'."""
        for i in range(10):
            await graph_store.upsert_node(GraphNode(id=f"fn_{i}", type=NodeType.FUNCTION, file_path=f"f{i}.py"))

        res = await enrichment_handlers.enrich_batch({"scope": "full"}, chain_ctx)
        assert res["enriched"] == 10

        node = await graph_store.get_node("fn_0")
        assert node.semantic.status == "enriched"

    @pytest.mark.asyncio
    async def test_chain_enrich_stale_full_scope(self, chain_ctx, graph_store):
        """Test: enrich_stale with scope='full'."""
        await graph_store.upsert_node(
            GraphNode(id="s1", type=NodeType.FUNCTION, file_path="f1.py", semantic=SemanticProperties(status="stale"))
        )
        await graph_store.upsert_node(
            GraphNode(
                id="s2", type=NodeType.FUNCTION, file_path="f2.py", semantic=SemanticProperties(status="no_metadata")
            )
        )
        await graph_store.upsert_node(
            GraphNode(
                id="s3", type=NodeType.FUNCTION, file_path="f3.py", semantic=SemanticProperties(status="enriched")
            )
        )

        res = await enrichment_handlers.enrich_stale({"scope": "full"}, chain_ctx)
        assert res["enriched"] == 2  # stale and no_metadata

        node1 = await graph_store.get_node("s1")
        assert node1.semantic.status == "enriched"
        node3 = await graph_store.get_node("s3")
        assert node3.semantic.status == "enriched"

    @pytest.mark.asyncio
    async def test_chain_annotate_bulk_all_missing(self, chain_ctx, graph_store):
        """Test: annotate_bulk where all nodes are missing."""
        res = await enrichment_handlers.annotate_bulk(
            {"annotations": [{"node_id": "ghost1", "description": "d1"}, {"node_id": "ghost2", "description": "d2"}]},
            chain_ctx,
        )
        assert res["annotated"] == 0
        assert len(res["missing"]) == 2

    @pytest.mark.asyncio
    async def test_chain_tag_set_empty_tags(self, chain_ctx, graph_store):
        """Test: tag set with empty tags list."""
        node_id = "tag_empty"
        await graph_store.upsert_node(
            GraphNode(id=node_id, type=NodeType.FUNCTION, file_path="f.py", semantic=SemanticProperties(tags=["t1"]))
        )

        await enrichment_handlers.tag({"scope": "f.py", "tags": [], "action": "set"}, chain_ctx)

        node = await graph_store.get_node(node_id)
        assert node.semantic.tags == []

    @pytest.mark.asyncio
    async def test_chain_enrich_batch_mixed_status(self, chain_ctx, graph_store):
        """Test: enrich_batch with mixed status."""
        await graph_store.upsert_node(
            GraphNode(id="n1", type=NodeType.FUNCTION, file_path="f.py", semantic=SemanticProperties(status="enriched"))
        )
        await graph_store.upsert_node(
            GraphNode(
                id="n2", type=NodeType.FUNCTION, file_path="f.py", semantic=SemanticProperties(status="no_metadata")
            )
        )

        res = await enrichment_handlers.enrich_batch({"scope": "f.py", "force": False}, chain_ctx)
        assert res["enriched"] == 1
        assert res["skipped"] == 1

    @pytest.mark.asyncio
    async def test_chain_tag_add_duplicate_tags(self, chain_ctx, graph_store):
        """Test: tag add with duplicate tags."""
        node_id = "dup_tag"
        await graph_store.upsert_node(
            GraphNode(id=node_id, type=NodeType.FUNCTION, file_path="f.py", semantic=SemanticProperties(tags=["t1"]))
        )

        await enrichment_handlers.tag({"scope": "f.py", "tags": ["t1", "t2"], "action": "add"}, chain_ctx)

        node = await graph_store.get_node(node_id)
        assert node.semantic.tags == ["t1", "t2"]  # No duplicates

    @pytest.mark.asyncio
    async def test_chain_enrich_single_node_force(self, chain_ctx, graph_store):
        """Test: enrich single node with force=True."""
        node_id = "f_enrich"
        await graph_store.upsert_node(
            GraphNode(
                id=node_id, type=NodeType.FUNCTION, file_path="f.py", semantic=SemanticProperties(status="enriched")
            )
        )

        res = await enrichment_handlers.enrich({"node_id": node_id, "force": True}, chain_ctx)
        assert res["enriched"] is True

    @pytest.mark.asyncio
    async def test_chain_annotate_bulk_mixed_exists(self, chain_ctx, graph_store):
        """Test: annotate_bulk with mixed existence."""
        await graph_store.upsert_node(GraphNode(id="e1", type=NodeType.FUNCTION, file_path="f1.py"))
        await graph_store.upsert_node(GraphNode(id="e2", type=NodeType.FUNCTION, file_path="f2.py"))

        res = await enrichment_handlers.annotate_bulk(
            {
                "annotations": [
                    {"node_id": "e1", "description": "d1"},
                    {"node_id": "m1", "description": "d2"},
                    {"node_id": "e2", "description": "d3"},
                ]
            },
            chain_ctx,
        )
        assert res["annotated"] == 2
        assert res["missing"] == ["m1"]

    @pytest.mark.asyncio
    async def test_chain_tag_scope_no_nodes(self, chain_ctx, graph_store):
        """Test: tag on scope with no nodes."""
        res = await enrichment_handlers.tag({"scope": "empty_scope", "tags": ["t"], "action": "add"}, chain_ctx)
        assert res["updated"] == 0
        assert res["total"] == 0

    @pytest.mark.asyncio
    async def test_chain_enrich_multiple_nodes(self, chain_ctx, graph_store):
        """Test: enrich multiple nodes in sequence."""
        for i in range(10):
            await graph_store.upsert_node(GraphNode(id=f"multi_{i}", type=NodeType.FUNCTION, file_path=f"f{i}.py"))

        enriched_count = 0
        for i in range(10):
            res = await enrichment_handlers.enrich({"node_id": f"multi_{i}"}, chain_ctx)
            if res.get("enriched"):
                enriched_count += 1

        assert enriched_count == 10

    @pytest.mark.asyncio
    async def test_chain_annotate_preserves_enrichment(self, chain_ctx, graph_store):
        """Test: annotate after enrich preserves enriched status."""
        node_id = "preserve_enrich"
        await graph_store.upsert_node(
            GraphNode(
                id=node_id, type=NodeType.FUNCTION, file_path="f.py", semantic=SemanticProperties(status="enriched")
            )
        )

        await enrichment_handlers.annotate({"node_id": node_id, "description": "desc", "tags": ["t"]}, chain_ctx)

        node = await graph_store.get_node(node_id)
        assert node.semantic.status == "enriched"
        assert node.semantic.description == "desc"

    @pytest.mark.asyncio
    async def test_chain_tag_with_special_chars(self, chain_ctx, graph_store):
        """Test: tag nodes with special characters in tags."""
        node_id = "special_tag"
        await graph_store.upsert_node(GraphNode(id=node_id, type=NodeType.FUNCTION, file_path="f.py"))

        await enrichment_handlers.tag(
            {"scope": "f.py", "tags": ["tag-with-dash", "tag_with_underscore", "tag.dot"], "action": "add"}, chain_ctx
        )

        node = await graph_store.get_node(node_id)
        assert "tag-with-dash" in node.semantic.tags
        assert "tag_with_underscore" in node.semantic.tags
        assert "tag.dot" in node.semantic.tags

    @pytest.mark.asyncio
    async def test_chain_enrich_status_query(self, chain_ctx, graph_store):
        """Test: query nodes by enrichment status."""
        await graph_store.upsert_node(
            GraphNode(id="e1", type=NodeType.FUNCTION, file_path="f.py", semantic=SemanticProperties(status="enriched"))
        )
        await graph_store.upsert_node(
            GraphNode(
                id="e2", type=NodeType.FUNCTION, file_path="f.py", semantic=SemanticProperties(status="no_metadata")
            )
        )
        await graph_store.upsert_node(
            GraphNode(id="e3", type=NodeType.FUNCTION, file_path="f.py", semantic=SemanticProperties(status="stale"))
        )

        res = await enrichment_handlers.enrich_status({"scope": "f.py"}, chain_ctx)
        assert res["total"] == 3

    @pytest.mark.asyncio
    async def test_chain_annotate_clears_manually_set(self, chain_ctx, graph_store):
        """Test: annotate with force overwrites a manually_set node (stays manual)."""
        node_id = "clear_manual"
        await graph_store.upsert_node(
            GraphNode(
                id=node_id,
                type=NodeType.FUNCTION,
                file_path="f.py",
                semantic=SemanticProperties(manually_set=True, description="old"),
            )
        )

        await enrichment_handlers.annotate({"node_id": node_id, "description": "new", "force": True}, chain_ctx)

        node = await graph_store.get_node(node_id)
        assert node.semantic.description == "new"
        # Annotate is itself a manual operation, so the flag remains set.
        assert node.semantic.manually_set is True

    @pytest.mark.asyncio
    async def test_chain_enrich_skips_manually_set(self, chain_ctx, graph_store):
        """Test: enrich skips nodes that are manually_set."""
        node_id = "manual_enrich_skip"
        await graph_store.upsert_node(
            GraphNode(
                id=node_id,
                type=NodeType.FUNCTION,
                file_path="f.py",
                semantic=SemanticProperties(manually_set=True, status="no_metadata"),
            )
        )

        res = await enrichment_handlers.enrich({"node_id": node_id, "force": False}, chain_ctx)
        assert res.get("skipped") is True

    @pytest.mark.asyncio
    async def test_chain_tag_multiple_scopes(self, chain_ctx, graph_store):
        """Test: tag nodes across multiple scopes."""
        await graph_store.upsert_node(GraphNode(id="s1", type=NodeType.FUNCTION, file_path="scope1/f.py"))
        await graph_store.upsert_node(GraphNode(id="s2", type=NodeType.FUNCTION, file_path="scope2/f.py"))

        await enrichment_handlers.tag({"scope": "scope1", "tags": ["scope1_tag"], "action": "add"}, chain_ctx)
        await enrichment_handlers.tag({"scope": "scope2", "tags": ["scope2_tag"], "action": "add"}, chain_ctx)

        node1 = await graph_store.get_node("s1")
        node2 = await graph_store.get_node("s2")
        assert "scope1_tag" in node1.semantic.tags
        assert "scope2_tag" in node2.semantic.tags


class TestHandlerChainWithMocks:
    """Integration tests for handler chains using mocks."""

    @pytest.fixture
    def mock_ctx(self, mock_graph_store, mock_vector_store):
        """Provide mock context for handler chain tests."""
        return {
            "graph": mock_graph_store,
            "vector": mock_vector_store,
            "principal": "mock_user",
            "correlation_id": "mock_corr_id",
        }

    @pytest.mark.asyncio
    async def test_mock_query_enrich_update(self, mock_ctx, mock_graph_store):
        """Test: mock chain query -> enrich -> update."""
        mock_graph_store.get_node = AsyncMock(
            return_value=GraphNode(id="mock_node", type=NodeType.FUNCTION, file_path="mock.py")
        )
        mock_graph_store.upsert_node = AsyncMock(return_value=None)

        await enrichment_handlers.enrich({"node_id": "mock_node"}, mock_ctx)

        mock_graph_store.upsert_node.assert_called_once()

    @pytest.mark.asyncio
    async def test_mock_annotate_bulk_with_mocks(self, mock_ctx, mock_graph_store):
        """Test: annotate_bulk with mocked graph store."""

        async def mock_get(node_id) -> GraphNode:
            return GraphNode(id=node_id, type=NodeType.FUNCTION, file_path="f.py")

        mock_graph_store.get_node = mock_get
        mock_graph_store.upsert_node = AsyncMock(return_value=None)

        res = await enrichment_handlers.annotate_bulk(
            {
                "annotations": [
                    {"node_id": "mock1", "description": "d1"},
                    {"node_id": "mock2", "description": "d2"},
                ]
            },
            mock_ctx,
        )

        assert res["annotated"] == 2

    @pytest.mark.asyncio
    async def test_mock_tag_with_mocks(self, mock_ctx, mock_graph_store):
        """Test: tag with mocked graph store."""

        async def mock_query_nodes(scope) -> list:
            return [
                GraphNode(id="m1", type=NodeType.FUNCTION, file_path=scope),
                GraphNode(id="m2", type=NodeType.FUNCTION, file_path=scope),
            ]

        mock_graph_store.find_nodes_by_scope = mock_query_nodes
        mock_graph_store.upsert_node = AsyncMock(return_value=None)

        res = await enrichment_handlers.tag({"scope": "mock_scope", "tags": ["mock_tag"], "action": "add"}, mock_ctx)

        assert res["updated"] == 2

    @pytest.mark.asyncio
    async def test_mock_enrich_batch_with_mocks(self, mock_ctx, mock_graph_store):
        """Test: enrich_batch with mocked store."""

        async def mock_query_nodes(scope) -> list:
            return [GraphNode(id=f"batch_{i}", type=NodeType.FUNCTION, file_path="f.py") for i in range(5)]

        mock_graph_store.find_nodes_by_scope = mock_query_nodes
        mock_graph_store.upsert_node = AsyncMock(return_value=None)

        res = await enrichment_handlers.enrich_batch({"scope": "mock_batch", "force": False}, mock_ctx)

        assert res["enriched"] == 5

    @pytest.mark.asyncio
    async def test_mock_enrich_stale_with_mocks(self, mock_ctx, mock_graph_store):
        """Test: enrich_stale with mocked store."""

        async def mock_query_nodes(scope) -> list:
            return [
                GraphNode(
                    id="stale_mock",
                    type=NodeType.FUNCTION,
                    file_path="f.py",
                    semantic=SemanticProperties(status="stale"),
                )
            ]

        mock_graph_store.find_nodes_by_scope = mock_query_nodes
        mock_graph_store.upsert_node = AsyncMock(return_value=None)

        res = await enrichment_handlers.enrich_stale({"scope": "mock_stale"}, mock_ctx)

        assert res["enriched"] == 1

    @pytest.mark.asyncio
    async def test_mock_enrich_status_with_mocks(self, mock_ctx, mock_graph_store):
        """Test: enrich_status with mocked store."""

        async def mock_query_nodes(scope) -> list:
            return [
                GraphNode(
                    id="e1",
                    type=NodeType.FUNCTION,
                    file_path="f.py",
                    semantic=SemanticProperties(status="enriched"),
                ),
                GraphNode(
                    id="e2",
                    type=NodeType.FUNCTION,
                    file_path="f.py",
                    semantic=SemanticProperties(status="stale"),
                ),
            ]

        mock_graph_store.find_nodes_by_scope = mock_query_nodes
        mock_graph_store.upsert_node = AsyncMock(return_value=None)

        res = await enrichment_handlers.enrich_status({"scope": "mock_status"}, mock_ctx)

        assert res["total"] == 2
        assert res["by_status"]["enriched"] == 1
        assert res["by_status"]["stale"] == 1

    @pytest.mark.asyncio
    async def test_mock_chain_multiple_operations(self, mock_ctx, mock_graph_store):
        """Test: multiple mock operations in chain."""
        calls = []

        async def mock_get(node_id) -> GraphNode:
            return GraphNode(id=node_id, type=NodeType.FUNCTION, file_path="chain.py")

        async def mock_upsert(node) -> None:
            calls.append(node.id)

        async def mock_get_scope(scope) -> list:
            return [GraphNode(id="chain1", type=NodeType.FUNCTION, file_path="chain.py")]

        mock_graph_store.get_node = mock_get
        mock_graph_store.upsert_node = mock_upsert
        mock_graph_store.find_nodes_by_scope = mock_get_scope

        await enrichment_handlers.enrich({"node_id": "chain1"}, mock_ctx)
        await enrichment_handlers.annotate({"node_id": "chain1", "description": "desc"}, mock_ctx)
        await enrichment_handlers.tag({"scope": "chain.py", "tags": ["tag"], "action": "add"}, mock_ctx)

        assert len(calls) >= 3

    @pytest.mark.asyncio
    async def test_mock_empty_result_handling(self, mock_ctx, mock_graph_store):
        """Test: handling empty results from mock store."""
        mock_graph_store.find_nodes_by_scope = AsyncMock(return_value=[])
        mock_graph_store.find_nodes = AsyncMock(return_value=[])
        mock_graph_store.get_node = AsyncMock(return_value=None)

        res_enrich = await enrichment_handlers.enrich({"node_id": "nonexistent"}, mock_ctx)
        assert res_enrich.get("error") == "node_not_found"

        res_tag = await enrichment_handlers.tag({"scope": "empty", "tags": ["t"], "action": "add"}, mock_ctx)
        assert res_tag["updated"] == 0

    @pytest.mark.asyncio
    async def test_mock_error_propagation(self, mock_ctx, mock_graph_store):
        """Test: error propagation in mock chain."""

        async def mock_upsert_error(node) -> None:
            raise RuntimeError("Mock upsert error")

        mock_graph_store.get_node = AsyncMock(
            return_value=GraphNode(id="error_node", type=NodeType.FUNCTION, file_path="f.py")
        )
        mock_graph_store.upsert_node = mock_upsert_error

        with pytest.raises(RuntimeError):
            await enrichment_handlers.enrich({"node_id": "error_node"}, mock_ctx)

    @pytest.mark.asyncio
    async def test_mock_batch_partial_failure(self, mock_ctx, mock_graph_store):
        """Test: batch operation with partial failure."""
        call_count = 0

        async def mock_upsert(node) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ValueError("Simulated failure")

        async def mock_query_nodes(scope) -> list:
            return [GraphNode(id=f"fail_{i}", type=NodeType.FUNCTION, file_path="f.py") for i in range(3)]

        mock_graph_store.query_nodes = mock_query_nodes
        mock_graph_store.upsert_node = mock_upsert

        res = await enrichment_handlers.enrich_batch({"scope": "fail_scope", "force": True}, mock_ctx)

        assert res.get("errors", 0) > 0 or res["enriched"] < 3


class TestHandlerChainEdgeCases:
    """Edge case tests for handler chains."""

    @pytest.fixture
    def edge_ctx(self, graph_store):
        """Provide context for edge case tests."""
        return {
            "engine": DefaultQueryEngine(graph_store=graph_store),
            "graph": graph_store,
            "principal": "edge_user",
            "correlation_id": "edge_corr_id",
        }

    @pytest.mark.asyncio
    async def test_very_long_tag_list(self, edge_ctx, graph_store):
        """Test: adding many tags at once."""
        node_id = "many_tags"
        await graph_store.upsert_node(GraphNode(id=node_id, type=NodeType.FUNCTION, file_path="f.py"))

        many_tags = [f"tag_{i}" for i in range(50)]
        await enrichment_handlers.tag({"scope": "f.py", "tags": many_tags, "action": "add"}, edge_ctx)

        node = await graph_store.get_node(node_id)
        assert len(node.semantic.tags) == 50

    @pytest.mark.asyncio
    async def test_deep_nested_scope(self, edge_ctx, graph_store):
        """Test: tag nodes in deeply nested paths."""
        deep_path = "a/b/c/d/e/f/g/h/i/j/k/l/module.py"
        node_id = "deep_node"
        await graph_store.upsert_node(GraphNode(id=node_id, type=NodeType.FUNCTION, file_path=deep_path))

        await enrichment_handlers.tag({"scope": "a/b/c", "tags": ["deep"], "action": "add"}, edge_ctx)

        node = await graph_store.get_node(node_id)
        assert "deep" in node.semantic.tags

    @pytest.mark.asyncio
    async def test_unicode_tags(self, edge_ctx, graph_store):
        """Test: handling unicode characters in tags."""
        node_id = "unicode_node"
        await graph_store.upsert_node(GraphNode(id=node_id, type=NodeType.FUNCTION, file_path="f.py"))

        unicode_tags = ["tag_emoji", "标签", "тег", "🔧"]
        await enrichment_handlers.tag({"scope": "f.py", "tags": unicode_tags, "action": "add"}, edge_ctx)

        node = await graph_store.get_node(node_id)
        for tag in unicode_tags:
            assert tag in node.semantic.tags

    @pytest.mark.asyncio
    async def test_concurrent_enrich_operations(self, edge_ctx, graph_store):
        """Test: concurrent enrich operations on same node."""
        node_id = "concurrent_node"
        await graph_store.upsert_node(GraphNode(id=node_id, type=NodeType.FUNCTION, file_path="f.py"))

        tasks = [enrichment_handlers.enrich({"node_id": node_id}, edge_ctx) for _ in range(5)]

        await asyncio.gather(*tasks)

        node = await graph_store.get_node(node_id)
        assert node.semantic.status == "enriched"

    @pytest.mark.asyncio
    async def test_rapid_chain_operations(self, edge_ctx, graph_store):
        """Test: rapid sequential chain operations."""
        node_id = "rapid_node"
        await graph_store.upsert_node(GraphNode(id=node_id, type=NodeType.FUNCTION, file_path="f.py"))

        for _ in range(20):
            await enrichment_handlers.enrich({"node_id": node_id}, edge_ctx)
            await enrichment_handlers.annotate({"node_id": node_id, "description": "rapid"}, edge_ctx)

        node = await graph_store.get_node(node_id)
        assert node.semantic.status == "enriched"
        assert node.semantic.description == "rapid"

    @pytest.mark.asyncio
    async def test_mixed_node_types_in_chain(self, edge_ctx, graph_store):
        """Test: chain operations on different node types."""
        nodes = [
            GraphNode(id="func_node", type=NodeType.FUNCTION, file_path="f.py"),
            GraphNode(id="class_node", type=NodeType.CLASS, file_path="c.py"),
            GraphNode(id="module_node", type=NodeType.PACKAGE, file_path="m.py"),
        ]

        for node in nodes:
            await graph_store.upsert_node(node)

        for node in nodes:
            await enrichment_handlers.enrich({"node_id": node.id}, edge_ctx)

        for node in nodes:
            retrieved = await graph_store.get_node(node.id)
            assert retrieved.semantic.status == "enriched"

    @pytest.mark.asyncio
    async def test_empty_scope_results(self, edge_ctx, graph_store):
        """Test: operations on non-existent scope."""
        res = await enrichment_handlers.enrich_batch({"scope": "nonexistent/path"}, edge_ctx)
        assert res["enriched"] == 0

        res = await enrichment_handlers.enrich_stale({"scope": "nonexistent/path"}, edge_ctx)
        assert res["enriched"] == 0

    @pytest.mark.asyncio
    async def test_whitespace_in_parameters(self, edge_ctx, graph_store):
        """Test: handling whitespace in parameters."""
        node_id = "ws_node"
        await graph_store.upsert_node(GraphNode(id=node_id, type=NodeType.FUNCTION, file_path=" f.py "))

        await enrichment_handlers.tag({"scope": " f.py ", "tags": [" ws_tag "], "action": "add"}, edge_ctx)

        node = await graph_store.get_node(node_id)
        assert len(node.semantic.tags) >= 1

    @pytest.mark.asyncio
    async def test_case_sensitivity_in_tags(self, edge_ctx, graph_store):
        """Test: case sensitivity in tag operations."""
        node_id = "case_node"
        await graph_store.upsert_node(
            GraphNode(id=node_id, type=NodeType.FUNCTION, file_path="f.py", semantic=SemanticProperties(tags=["Tag"]))
        )

        await enrichment_handlers.tag({"scope": "f.py", "tags": ["tag"], "action": "add"}, edge_ctx)
        await enrichment_handlers.tag({"scope": "f.py", "tags": ["TAG"], "action": "add"}, edge_ctx)

        node = await graph_store.get_node(node_id)
        assert "Tag" in node.semantic.tags
        assert "tag" in node.semantic.tags
        assert "TAG" in node.semantic.tags
