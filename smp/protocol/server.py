"""FastAPI application with JSON-RPC 2.0 endpoint.

Start with: ``python3.11 -m smp.cli serve``
"""

from __future__ import annotations

try:
    import sys

    import pysqlite3

    sys.modules["sqlite3"] = pysqlite3
except ImportError:
    pass

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import Response

from smp.core.merkle import MerkleIndex, MerkleTree
from smp.engine.community import CommunityDetector
from smp.engine.embedding import create_embedding_service
from smp.engine.enricher import StaticSemanticEnricher
from smp.engine.graph_builder import DefaultGraphBuilder
from smp.engine.seed_walk import SeedWalkEngine
from smp.engine.query import DefaultQueryEngine
from smp.logging import get_logger
from smp.parser.registry import ParserRegistry
from smp.protocol.dispatcher import handle_rpc
from smp.store.chroma_store import ChromaVectorStore
from smp.store.graph.neo4j_store import Neo4jGraphStore

log = get_logger(__name__)


def create_app(
    neo4j_uri: str | None = None,
    neo4j_user: str | None = None,
    neo4j_password: str | None = None,
    safety_enabled: bool = False,
) -> FastAPI:
    """Create and configure the SMP FastAPI application."""

    uri = neo4j_uri or os.environ.get("SMP_NEO4J_URI", "bolt://localhost:7687")
    user = neo4j_user or os.environ.get("SMP_NEO4J_USER", "neo4j")
    password = neo4j_password or os.environ.get("SMP_NEO4J_PASSWORD", "")

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]  # noqa: ANN202
        graph = Neo4jGraphStore(uri=uri, user=user, password=password)
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

        safety: dict[str, Any] | None = None
        if safety_enabled:
            from smp.engine.handoff import HandoffManager
            from smp.engine.integrity import IntegrityVerifier
            from smp.engine.safety import (
                AuditLogger,
                CheckpointManager,
                DryRunSimulator,
                GuardEngine,
                LockManager,
                SessionManager,
            )
            from smp.engine.telemetry import TelemetryEngine
            from smp.sandbox.executor import SandboxExecutor
            from smp.sandbox.spawner import SandboxSpawner

            session_manager = SessionManager(graph_store=graph)
            lock_manager = LockManager(graph_store=graph)
            session_manager.set_graph_store(graph)
            lock_manager.set_graph_store(graph)
            sandbox_spawner = SandboxSpawner()
            sandbox_executor = SandboxExecutor()
            telemetry_engine = TelemetryEngine()
            handoff_manager = HandoffManager()
            integrity_verifier = IntegrityVerifier()

            # Runtime linker and linker are already available in the graph
            # We'll add them to app.state for access via context
            app.state.telemetry_engine = telemetry_engine
            app.state.handoff_manager = handoff_manager
            app.state.integrity_verifier = integrity_verifier

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

        app.state.graph = graph
        app.state.vector = vector
        app.state.engine = engine
        app.state.community_detector = community_detector
        app.state.merkle_index = merkle_index
        app.state.builder = builder
        app.state.enricher = enricher
        app.state.registry = registry
        app.state.safety = safety

        log.info("server_started", neo4j=neo4j_uri, safety=safety_enabled)
        yield

        await graph.close()
        log.info("server_stopped")

    app = FastAPI(title="SMP — Structural Memory Protocol", version="3.0.0", lifespan=lifespan)

    @app.post("/rpc")
    async def rpc_endpoint(request: Request) -> Response:
        return await handle_rpc(
            request,
            engine=app.state.engine,
            enricher=app.state.enricher,
            builder=app.state.builder,
            registry=app.state.registry,
            vector=app.state.vector,
            safety=app.state.safety,
            telemetry_engine=getattr(app.state, "telemetry_engine", None),
            handoff_manager=getattr(app.state, "handoff_manager", None),
            integrity_verifier=getattr(app.state, "integrity_verifier", None),
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/stats")
    async def stats() -> dict[str, int]:
        graph: Neo4jGraphStore = app.state.graph
        return {
            "nodes": await graph.count_nodes(),
            "edges": await graph.count_edges(),
        }

    return app


app = create_app()
