#!/usr/bin/env python3.11
"""Comprehensive test suite for SMP MCP tools."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Add SMP to path
sys.path.insert(0, str(Path(__file__).parent))

from smp.core.merkle import MerkleIndex, MerkleTree
from smp.engine.community import CommunityDetector
from smp.engine.embedding import create_embedding_service
from smp.engine.enricher import StaticSemanticEnricher
from smp.engine.graph_builder import DefaultGraphBuilder
from smp.engine.query import DefaultQueryEngine
from smp.engine.seed_walk import SeedWalkEngine
from smp.logging import get_logger
from smp.parser.registry import ParserRegistry
from smp.protocol.dispatcher import get_dispatcher
from smp.store.chroma_store import ChromaVectorStore
from smp.store.graph.neo4j_store import Neo4jGraphStore

log = get_logger(__name__)


class TestResult:
    """Track test results."""

    def __init__(self) -> None:
        self.total = 0
        self.passed = 0
        self.failed = 0
        self.results: dict[str, dict[str, Any]] = {}

    def add(self, tool_name: str, passed: bool, message: str = "", error: str = "") -> None:
        """Add test result."""
        self.total += 1
        if passed:
            self.passed += 1
            status = "✓ PASS"
        else:
            self.failed += 1
            status = "✗ FAIL"

        self.results[tool_name] = {
            "status": status,
            "message": message,
            "error": error,
        }
        print(f"{status:8} {tool_name:30} {message}")

    def summary(self) -> None:
        """Print summary."""
        print("\n" + "=" * 80)
        print(f"Test Summary: {self.passed}/{self.total} tests passed")
        print("=" * 80)
        if self.failed > 0:
            print(f"\n{self.failed} tests failed:")
            for tool, result in self.results.items():
                if "FAIL" in result["status"]:
                    print(f"  - {tool}: {result['error']}")


async def test_tools() -> None:
    """Test all MCP tools."""
    print("=" * 80)
    print("SMP MCP Tools Test Suite")
    print("=" * 80 + "\n")

    # Initialize state
    print("Setting up SMP services...")
    graph = Neo4jGraphStore(uri="bolt://localhost:7687", user="neo4j", password="123456789$Do")
    await graph.connect()

    vector = ChromaVectorStore()
    await vector.connect()

    embedding_service = create_embedding_service()
    await embedding_service.connect()

    enricher = StaticSemanticEnricher(embedding_service=embedding_service)
    community_detector = CommunityDetector(graph_store=graph, vector_store=vector)
    default_engine = DefaultQueryEngine(graph_store=graph, enricher=enricher)
    engine = SeedWalkEngine(graph_store=graph, vector_store=vector, enricher=enricher, delegate=default_engine)
    builder = DefaultGraphBuilder(graph)
    registry = ParserRegistry()
    merkle_index = MerkleIndex(MerkleTree())

    state = {
        "graph": graph,
        "vector": vector,
        "engine": engine,
        "community_detector": community_detector,
        "merkle_index": merkle_index,
        "builder": builder,
        "enricher": enricher,
        "registry": registry,
        "safety": None,
        "telemetry_engine": None,
        "handoff_manager": None,
        "integrity_verifier": None,
    }

    context = {
        "engine": state["engine"],
        "enricher": state["enricher"],
        "builder": state["builder"],
        "registry": state["registry"],
        "vector": state["vector"],
        "safety": state["safety"],
        "telemetry_engine": state["telemetry_engine"],
        "handoff_manager": state["handoff_manager"],
        "integrity_verifier": state["integrity_verifier"],
    }

    dispatcher = get_dispatcher()
    results = TestResult()

    print("Services initialized. Starting tests...\n")
    print("Graph Intelligence Tools")
    print("-" * 80)

    # Graph Intelligence Tools
    try:
        handler = dispatcher.get_handler("smp/navigate")
        result = await handler.handle({"query": "authenticate_user", "include_relationships": True}, context)
        results.add("smp_navigate", bool(result), "Found entities" if result else "No results")
    except Exception as e:
        results.add("smp_navigate", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/trace")
        result = await handler.handle(
            {"start": "authenticate_user", "relationship": "CALLS", "depth": 2, "direction": "outgoing"},
            context,
        )
        results.add("smp_trace", bool(result), "Traced dependencies" if result else "No trace")
    except Exception as e:
        results.add("smp_trace", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/context")
        result = await handler.handle(
            {"file_path": "src/auth/manager.py", "scope": "edit", "depth": 2}, context
        )
        results.add("smp_context", bool(result), "Got file context" if result else "No context")
    except Exception as e:
        results.add("smp_context", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/impact")
        result = await handler.handle({"entity": "authenticate_user", "change_type": "delete"}, context)
        results.add("smp_impact", bool(result), "Analyzed impact" if result else "No impact data")
    except Exception as e:
        results.add("smp_impact", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/locate")
        result = await handler.handle(
            {"query": "authenticate", "fields": ["name", "docstring"], "node_types": [], "top_k": 5},
            context,
        )
        results.add("smp_locate", bool(result), f"Located {len(result) if result else 0} entities")
    except Exception as e:
        results.add("smp_locate", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/search")
        result = await handler.handle(
            {"query": "authentication", "match": "any", "filter": {}, "top_k": 5}, context
        )
        results.add("smp_search", bool(result is not None), "Performed semantic search")
    except Exception as e:
        results.add("smp_search", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/flow")
        result = await handler.handle(
            {"start": "authenticate_user", "end": "get_user", "flow_type": "data"}, context
        )
        results.add("smp_flow", bool(result is not None), "Found flow" if result else "No flow")
    except Exception as e:
        results.add("smp_flow", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/graph/why")
        result = await handler.handle({"entity": "authenticate_user", "relationship": "CALLS", "depth": 2}, context)
        results.add("smp_why", bool(result is not None), "Explained relationship" if result else "No explanation")
    except Exception as e:
        results.add("smp_why", False, error=str(e))

    print("\nMemory & Update Tools")
    print("-" * 80)

    # Memory & Update Tools
    try:
        handler = dispatcher.get_handler("smp/update")
        result = await handler.handle(
            {
                "file_path": "src/test_new.py",
                "content": "def hello():\n    return 'world'",
                "change_type": "added",
                "language": "python",
            },
            context,
        )
        results.add("smp_update", bool(result), "Updated file" if result else "No update result")
    except Exception as e:
        results.add("smp_update", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/batch_update")
        result = await handler.handle(
            {
                "changes": [
                    {
                        "file_path": "src/batch_test1.py",
                        "content": "def func1():\n    pass",
                        "change_type": "added",
                        "language": "python",
                    }
                ]
            },
            context,
        )
        results.add("smp_batch_update", bool(result), "Batch updated files" if result else "No batch result")
    except Exception as e:
        results.add("smp_batch_update", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/reindex")
        result = await handler.handle({"scope": "partial"}, context)
        results.add("smp_reindex", bool(result is not None), "Reindexed graph")
    except Exception as e:
        results.add("smp_reindex", False, error=str(e))

    print("\nEnrichment Tools")
    print("-" * 80)

    # Enrichment Tools
    try:
        # First, get a real node ID from the graph
        handler = dispatcher.get_handler("smp/locate")
        nodes = await handler.handle(
            {"query": "authenticate_user", "fields": ["name"], "node_types": ["Function"], "top_k": 1}, context
        )
        if nodes and len(nodes) > 0:
            node_id = nodes[0].get("id", "authenticate_user")
        else:
            node_id = "authenticate_user"

        handler = dispatcher.get_handler("smp/enrich")
        result = await handler.handle({"node_id": node_id, "force": False}, context)
        results.add("smp_enrich", bool(result is not None), "Enriched node")
    except Exception as e:
        results.add("smp_enrich", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/enrich/batch")
        result = await handler.handle({"scope": "stale", "force": False}, context)
        results.add("smp_enrich_batch", bool(result is not None), "Batch enriched nodes")
    except Exception as e:
        results.add("smp_enrich_batch", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/enrich/stale")
        result = await handler.handle({"scope": "full"}, context)
        results.add("smp_enrich_stale", bool(result is not None), f"Found stale nodes")
    except Exception as e:
        results.add("smp_enrich_stale", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/enrich/status")
        result = await handler.handle({"scope": "full"}, context)
        results.add("smp_enrich_status", bool(result is not None), "Got enrichment status")
    except Exception as e:
        results.add("smp_enrich_status", False, error=str(e))

    print("\nAnnotation & Tagging Tools")
    print("-" * 80)

    # Annotation Tools
    try:
        handler = dispatcher.get_handler("smp/annotate")
        result = await handler.handle(
            {"node_id": "authenticate_user", "description": "Test annotation", "tags": ["test"], "force": False},
            context,
        )
        results.add("smp_annotate", bool(result is not None), "Annotated node")
    except Exception as e:
        results.add("smp_annotate", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/annotate/bulk")
        result = await handler.handle(
            {"annotations": [{"node_id": "authenticate_user", "tags": ["auth", "security"]}]}, context
        )
        results.add("smp_annotate_bulk", bool(result is not None), "Bulk annotated nodes")
    except Exception as e:
        results.add("smp_annotate_bulk", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/tag")
        result = await handler.handle(
            {"scope": "src/auth/manager.py", "tags": ["auth-module"], "action": "add"}, context
        )
        results.add("smp_tag", bool(result is not None), "Tagged entities")
    except Exception as e:
        results.add("smp_tag", False, error=str(e))

    print("\nCommunity Detection Tools")
    print("-" * 80)

    # Community Detection Tools
    try:
        handler = dispatcher.get_handler("smp/community/detect")
        result = await handler.handle({"algorithm": "louvain", "resolution": 1.0}, context)
        results.add("smp_community_detect", bool(result is not None), "Detected communities")
    except Exception as e:
        results.add("smp_community_detect", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/community/members")
        result = await handler.handle({"community_id": "0"}, context)
        results.add("smp_community_members", bool(result is not None), "Got community members")
    except Exception as e:
        results.add("smp_community_members", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/community/stats")
        result = await handler.handle({}, context)
        results.add("smp_community_stats", bool(result is not None), "Got community stats")
    except Exception as e:
        results.add("smp_community_stats", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/community/graph")
        result = await handler.handle({"format": "json"}, context)
        results.add("smp_community_graph", bool(result is not None), "Got community graph")
    except Exception as e:
        results.add("smp_community_graph", False, error=str(e))

    print("\nMerkle & Verification Tools")
    print("-" * 80)

    # Merkle & Verification Tools
    try:
        handler = dispatcher.get_handler("smp/merkle/index")
        result = await handler.handle({"file_path": "src/auth/manager.py"}, context)
        results.add("smp_merkle_index", bool(result is not None), "Got merkle index")
    except Exception as e:
        results.add("smp_merkle_index", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/merkle/verify")
        result = await handler.handle({"file_path": "src/auth/manager.py", "tree": {}}, context)
        results.add("smp_merkle_verify", bool(result is not None), "Verified merkle tree")
    except Exception as e:
        results.add("smp_merkle_verify", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/verify_integrity")
        result = await handler.handle(
            {"node_id": "authenticate_user", "current_state": {}}, context
        )
        results.add("smp_verify_integrity", bool(result is not None), "Verified integrity")
    except Exception as e:
        results.add("smp_verify_integrity", False, error=str(e))

    print("\nSafety & Session Tools")
    print("-" * 80)

    # Safety & Session Tools
    try:
        handler = dispatcher.get_handler("smp/session/open")
        result = await handler.handle(
            {"mode": "read", "scope": ["src/auth/manager.py"], "task": "Test read session"},
            context,
        )
        session_id = result.get("session_id") if result else None
        results.add("smp_session_open", bool(session_id), f"Opened session {session_id[:8]}" if session_id else "")
    except Exception as e:
        results.add("smp_session_open", False, error=str(e))
        session_id = None

    try:
        if session_id:
            handler = dispatcher.get_handler("smp/session/close")
            result = await handler.handle({"session_id": session_id, "status": "completed"}, context)
            results.add("smp_session_close", bool(result is not None), "Closed session")
    except Exception as e:
        results.add("smp_session_close", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/guard/check")
        result = await handler.handle(
            {"session_id": "test-session", "target": "authenticate_user", "intended_change": "delete"},
            context,
        )
        results.add("smp_guard_check", bool(result is not None), "Guard check passed")
    except Exception as e:
        results.add("smp_guard_check", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/checkpoint")
        result = await handler.handle({"session_id": "test-session", "files": ["src/auth/manager.py"]}, context)
        checkpoint_id = result.get("checkpoint_id") if result else None
        results.add("smp_checkpoint", bool(checkpoint_id), "Created checkpoint")
    except Exception as e:
        results.add("smp_checkpoint", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/dryrun")
        result = await handler.handle(
            {
                "session_id": "test-session",
                "file_path": "src/auth/manager.py",
                "proposed_content": "# Modified",
                "change_summary": "Test change",
            },
            context,
        )
        results.add("smp_dryrun", bool(result is not None), "Dry run executed")
    except Exception as e:
        results.add("smp_dryrun", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/lock")
        result = await handler.handle({"session_id": "test-session", "files": ["src/auth/manager.py"]}, context)
        results.add("smp_lock", bool(result is not None), "Locked files")
    except Exception as e:
        results.add("smp_lock", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/unlock")
        result = await handler.handle({"session_id": "test-session", "files": ["src/auth/manager.py"]}, context)
        results.add("smp_unlock", bool(result is not None), "Unlocked files")
    except Exception as e:
        results.add("smp_unlock", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/rollback")
        result = await handler.handle({"session_id": "test-session", "checkpoint_id": "test-checkpoint"}, context)
        results.add("smp_rollback", bool(result is not None), "Rollback executed")
    except Exception as e:
        results.add("smp_rollback", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/audit/get")
        result = await handler.handle({"audit_log_id": "test-log"}, context)
        results.add("smp_audit_get", bool(result is not None), "Retrieved audit log")
    except Exception as e:
        results.add("smp_audit_get", False, error=str(e))

    print("\nSandbox Tools")
    print("-" * 80)

    # Sandbox Tools
    try:
        handler = dispatcher.get_handler("smp/sandbox/spawn")
        result = await handler.handle({"name": "test-sandbox", "template": None, "files": {}}, context)
        sandbox_id = result.get("sandbox_id") if result else None
        results.add("smp_sandbox_spawn", bool(sandbox_id), f"Spawned sandbox {sandbox_id[:8] if sandbox_id else ''}")
    except Exception as e:
        results.add("smp_sandbox_spawn", False, error=str(e))
        sandbox_id = None

    try:
        if sandbox_id:
            handler = dispatcher.get_handler("smp/sandbox/execute")
            result = await handler.handle(
                {"command": ["echo", "hello"], "stdin": None, "working_directory": None},
                context,
            )
            results.add("smp_sandbox_execute", bool(result is not None), "Executed command")
    except Exception as e:
        results.add("smp_sandbox_execute", False, error=str(e))

    try:
        if sandbox_id:
            handler = dispatcher.get_handler("smp/sandbox/destroy")
            result = await handler.handle({"sandbox_id": sandbox_id}, context)
            results.add("smp_sandbox_destroy", bool(result is not None), "Destroyed sandbox")
    except Exception as e:
        results.add("smp_sandbox_destroy", False, error=str(e))

    print("\nHandoff & Coordination Tools")
    print("-" * 80)

    # Handoff & Coordination Tools
    try:
        handler = dispatcher.get_handler("smp/handoff/review")
        result = await handler.handle(
            {
                "files_changed": ["src/auth/manager.py"],
                "reviewers": ["reviewer1"],
                "diff_summary": "Test changes",
            },
            context,
        )
        review_id = result.get("review_id") if result else None
        results.add("smp_handoff_review", bool(review_id), f"Created review {review_id[:8] if review_id else ''}")
    except Exception as e:
        results.add("smp_handoff_review", False, error=str(e))
        review_id = None

    try:
        if review_id:
            handler = dispatcher.get_handler("smp/handoff/approve")
            result = await handler.handle({"review_id": review_id, "reviewer": "reviewer1"}, context)
            results.add("smp_handoff_approve", bool(result is not None), "Approved review")
    except Exception as e:
        results.add("smp_handoff_approve", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/handoff/reject")
        result = await handler.handle(
            {"review_id": "test-review", "reviewer": "reviewer1", "reason": "Test rejection"},
            context,
        )
        results.add("smp_handoff_reject", bool(result is not None), "Rejected review")
    except Exception as e:
        results.add("smp_handoff_reject", False, error=str(e))

    try:
        handler = dispatcher.get_handler("smp/handoff/pr")
        result = await handler.handle(
            {
                "review_id": "test-review",
                "title": "Test PR",
                "body": "Test PR body",
                "branch": "test-branch",
                "base_branch": "main",
            },
            context,
        )
        results.add("smp_handoff_pr", bool(result is not None), "Created pull request")
    except Exception as e:
        results.add("smp_handoff_pr", False, error=str(e))

    print("\nTelemetry Tools")
    print("-" * 80)

    # Telemetry Tools
    try:
        handler = dispatcher.get_handler("smp/telemetry")
        result = await handler.handle({"action": "get_stats", "node_id": None, "threshold": None}, context)
        results.add("smp_telemetry", bool(result is not None), "Retrieved telemetry stats")
    except Exception as e:
        results.add("smp_telemetry", False, error=str(e))

    # Print summary
    await graph.close()
    results.summary()

    # Exit with appropriate code
    sys.exit(0 if results.failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(test_tools())
