"""FastAPI application with JSON-RPC 2.0 endpoint.

Start with: ``python3.11 -m smp.cli serve``
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import Response

from smp.engine.enricher import LLMSemanticEnricher
from smp.engine.graph_builder import DefaultGraphBuilder
from smp.engine.query import DefaultQueryEngine
from smp.logging import get_logger
from smp.parser.registry import ParserRegistry
from smp.protocol.router import handle_rpc
from smp.store.graph.neo4j_store import Neo4jGraphStore
from smp.store.vector.chroma_store import ChromaVectorStore

log = get_logger(__name__)


def create_app(
    neo4j_uri: str = "bolt://localhost:7687",
    neo4j_user: str = "neo4j",
    neo4j_password: str = "123456789$Do",
    gemini_api_key: str | None = None,
    persist_dir: str | None = None,
) -> FastAPI:
    """Create and configure the SMP FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # --- Startup ---
        graph = Neo4jGraphStore(uri=neo4j_uri, user=neo4j_user, password=neo4j_password)
        await graph.connect()

        vector = ChromaVectorStore(persist_directory=persist_dir)
        await vector.connect()

        enricher = LLMSemanticEnricher(api_key=gemini_api_key)
        engine = DefaultQueryEngine(graph, vector, enricher)
        builder = DefaultGraphBuilder(graph)
        registry = ParserRegistry()

        # Store components on app state
        app.state.graph = graph
        app.state.vector = vector
        app.state.engine = engine
        app.state.builder = builder
        app.state.enricher = enricher
        app.state.registry = registry

        log.info(
            "server_started",
            neo4j=neo4j_uri,
            llm=enricher.has_llm,
        )
        yield

        # --- Shutdown ---
        await graph.close()
        await vector.close()
        log.info("server_stopped")

    app = FastAPI(title="SMP — Structural Memory Protocol", version="0.1.0", lifespan=lifespan)

    @app.post("/rpc")
    async def rpc_endpoint(request: Request) -> Response:
        return await handle_rpc(
            request,
            engine=app.state.engine,
            enricher=app.state.enricher,
            builder=app.state.builder,
            registry=app.state.registry,
            vector=app.state.vector,
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


# Default app instance for `uvicorn smp.protocol.server:app`
app = create_app()
