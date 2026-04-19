#!/usr/bin/env python3.11
"""Test MCP tools WITH safety features enabled."""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path
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
from smp.engine.handoff import HandoffManager
from smp.engine.integrity import IntegrityVerifier
from smp.engine.safety import (
    AuditLogger, CheckpointManager, DryRunSimulator, GuardEngine, LockManager, SessionManager,
)
from smp.engine.telemetry import TelemetryEngine
from smp.sandbox.executor import SandboxExecutor
from smp.sandbox.spawner import SandboxSpawner

log = get_logger(__name__)

class TestResult:
    def __init__(self):
        self.total = 0
        self.passed = 0
        self.failed = 0
        self.results = {}

    def add(self, tool_name, passed, message="", error=""):
        self.total += 1
        if passed:
            self.passed += 1
            status = "✓ PASS"
        else:
            self.failed += 1
            status = "✗ FAIL"
        self.results[tool_name] = {"status": status, "message": message, "error": error}
        print(f"{status:8} {tool_name:30} {message}")

    def summary(self):
        print("\n" + "=" * 80)
        print(f"Test Summary: {self.passed}/{self.total} tests passed")
        print("=" * 80)
        if self.failed > 0:
            print(f"\n{self.failed} tests failed:")
            for tool, result in self.results.items():
                if "FAIL" in result["status"]:
                    print(f"  - {tool}: {result['error']}")

async def test_safety_tools():
    print("=" * 80)
    print("SMP Safety & Coordination Tools Test")
    print("=" * 80 + "\n")

    # Initialize with safety enabled
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

    # Initialize safety components
    session_manager = SessionManager(graph_store=graph)
    lock_manager = LockManager(graph_store=graph)
    session_manager.set_graph_store(graph)
    lock_manager.set_graph_store(graph)
    sandbox_spawner = SandboxSpawner()
    sandbox_executor = SandboxExecutor()
    telemetry_engine = TelemetryEngine()
    handoff_manager = HandoffManager()
    integrity_verifier = IntegrityVerifier()

    safety = {
        "session_manager": session_manager,
        "lock_manager": lock_manager,
        "guard_engine": GuardEngine(session_manager, lock_manager),
        "dryrun_simulator": DryRunSimulator(),
        "checkpoint_manager": CheckpointManager(),
        "audit_logger": AuditLogger(),
        "sandbox_spawner": sandbox_spawner,
        "sandbox_executor": sandbox_executor,
    }

    state = {
        "graph": graph,
        "vector": vector,
        "engine": engine,
        "community_detector": community_detector,
        "merkle_index": merkle_index,
        "builder": builder,
        "enricher": enricher,
        "registry": registry,
        "safety": safety,
        "telemetry_engine": telemetry_engine,
        "handoff_manager": handoff_manager,
        "integrity_verifier": integrity_verifier,
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

    print("Safety & Session Tools\n" + "-" * 80)

    try:
        handler = dispatcher.get_handler("smp/session/open")
        result = await handler.handle(
            {"mode": "read", "scope": ["src/auth/manager.py"], "task": "Test read session"},
            context,
        )
        session_id = result.get("session_id") if result else None
        results.add("smp_session_open", bool(session_id), f"Opened session {session_id[:8] if session_id else ''}")
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

    print("\nHandoff & Coordination Tools\n" + "-" * 80)

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

    await graph.close()
    results.summary()
    sys.exit(0 if results.failed == 0 else 1)

if __name__ == "__main__":
    asyncio.run(test_safety_tools())
