from __future__ import annotations

import asyncio
from typing import Any
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP
from smp.engine.query import DefaultQueryEngine
from smp.store.graph.neo4j_store import Neo4jGraphStore

# Configuration
NEO4J_URI = "bolt://localhost:7688"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "TestPassword123"

# State to hold the engine
_engine: DefaultQueryEngine | None = None
_store: Neo4jGraphStore | None = None


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncGenerator[dict[str, Any], None]:
    """Initialize resources before server accepts requests."""
    global _engine, _store
    _store = Neo4jGraphStore(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)
    await _store.connect()
    _engine = DefaultQueryEngine(_store)
    yield {"engine": _engine, "store": _store}
    if _store:
        await _store.close()


# Initialize FastMCP server
mcp = FastMCP("SMP-Code-Intelligence", lifespan=lifespan)

@mcp.tool()
async def smp_locate(query: str) -> str:
    """Locate entities (functions, classes, files) by name or keyword.
    
    Args:
        query: The name or keyword to search for.
    """
    results = await _engine.locate(query)
    return str(results)

@mcp.tool()
async def smp_navigate(entity: str) -> str:
    """Navigate to a specific entity to see its details and relationships.
    
    Args:
        entity: The entity name or ID (e.g., 'calculate_order_cost').
    """
    result = await _engine.navigate(entity)
    return str(result)


@mcp.tool()
async def smp_flow(start: str, end: str) -> str:
    """Find the call flow/path between two entities.
    
    Args:
        start: The starting entity.
        end: The destination entity.
    """
    result = await _engine.find_flow(start, end)
    return str(result)


@mcp.tool()
async def smp_impact(entity: str, change_type: str = "delete") -> str:
    """Analyze the impact of changing or deleting an entity.
    
    Args:
        entity: The entity to analyze (supports 'file:type:name' format).
        change_type: The type of change ('delete', 'modify').
    """
    result = await _engine.assess_impact(entity, change_type)
    return str(result)


@mcp.tool()
async def smp_search(query: str) -> str:
    """Search for entities using a keyword across the codebase.
    
    Args:
        query: Keyword to search for.
    """
    result = await _engine.search(query)
    return str(result)
