"""MCP (Model Context Protocol) server for SMP.

Wraps all SMP JSON-RPC handlers as MCP tools so AI agents (Claude,
etc.) can query and manipulate the code knowledge graph through the
standard MCP interface.

Start with::

    python3.11 -m smp.protocol.mcp

Or for Claude Desktop integration, add to ``claude_desktop_config.json``::

    {
      "mcpServers": {
        "smp": {
          "command": "python3.11",
          "args": ["-m", "smp.protocol.mcp"],
          "cwd": "/path/to/SMP"
        }
      }
    }
"""

from __future__ import annotations

import json as _json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from smp.core.config import Settings
from smp.engine.graph_builder import DefaultGraphBuilder
from smp.engine.query import DefaultQueryEngine
from smp.logging import get_logger
from smp.protocol.server import _HANDLERS, _MethodNotFoundError
from smp.protocol.server import _dispatch as rpc_dispatch
from smp.store.graph.mmap_store import MMapGraphStore
from smp.vector.mmap_vector import MMapVectorStore

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Server state
# ---------------------------------------------------------------------------


class _ServerState:
    """Holds references to store / engine instances shared by all tools."""

    def __init__(self) -> None:
        self.graph: MMapGraphStore | None = None
        self.vector_store: MMapVectorStore | None = None
        self.engine: DefaultQueryEngine | None = None
        self.builder: DefaultGraphBuilder | None = None


_state = _ServerState()


def _get_context(ctx: Any) -> dict[str, Any]:
    """Build the runtime context dict that RPC handlers expect."""
    request_id = ctx.request_id if hasattr(ctx, "request_id") else None
    return {
        "graph": _state.graph,
        "vector_store": _state.vector_store,
        "engine": _state.engine,
        "builder": _state.builder,
        "principal": None,
        "correlation_id": request_id,
    }


async def _call_rpc(method: str, params: dict[str, Any], ctx: Any) -> Any:
    """Call an SMP RPC handler through the dispatcher."""
    runtime_ctx = _get_context(ctx)
    return await rpc_dispatch(method, params, runtime_ctx)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[None]:
    """Initialize stores and engines on startup, tear down on shutdown."""
    settings = Settings.from_env()
    resolved_graph_path = settings.graph_path
    Path(resolved_graph_path).parent.mkdir(parents=True, exist_ok=True)

    graph = MMapGraphStore(path=resolved_graph_path)
    await graph.connect()

    from smp.embedding.service import (
        EMBEDDING_DIM,
        get_embedding_service,  # noqa: F401
    )

    vector_store = MMapVectorStore(path=settings.vector_path, dimension=EMBEDDING_DIM)
    await vector_store.connect()

    engine = DefaultQueryEngine(graph_store=graph)
    builder = DefaultGraphBuilder(graph)

    _state.graph = graph
    _state.vector_store = vector_store
    _state.engine = engine
    _state.builder = builder

    log.info(
        "mcp_server_started",
        graph_path=resolved_graph_path,
        tools=len(_HANDLERS),
    )

    try:
        yield
    finally:
        await graph.close()
        await vector_store.close()
        log.info("mcp_server_stopped")


# ---------------------------------------------------------------------------
# MCP application
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "SMP — Structural Memory Protocol",
    lifespan=app_lifespan,
)


# ---------------------------------------------------------------------------
# Helper: Register MCP tools for RPC methods not covered by explicit wrappers
# ---------------------------------------------------------------------------


def _make_tool(method_name: str) -> None:
    """Factory that registers an MCP tool for *method_name*."""
    handler_fn = _HANDLERS[method_name]
    doc = (handler_fn.__doc__ or "").strip()
    doc_first_line = doc.split("\n")[0] if doc else f"SMP RPC: {method_name}"
    tool_name = method_name.replace("/", "_")

    @mcp.tool(name=tool_name, description=doc_first_line)
    async def tool_fn(params: str = "{}", ctx: Any = None) -> str:
        # NOTE: `method_name` is bound per `_make_tool()` call, so each
        # registered tool keeps its own method (no late-binding issue).
        try:
            parsed = _json.loads(params) if isinstance(params, str) else params
        except _json.JSONDecodeError as exc:
            return _json.dumps({"error": f"Invalid JSON params: {exc}"})

        try:
            result = await _call_rpc(method_name, parsed, ctx)
        except _MethodNotFoundError:
            return _json.dumps({"error": f"Method not found: {method_name}"})
        except Exception as exc:  # noqa: BLE001
            log.exception("mcp_tool_error", method=method_name, error=str(exc))
            return _json.dumps({"error": str(exc)[:500]})

        return _json.dumps(result, default=str, indent=2)


# Explicitly-wrapped methods (typed params) — don't auto-register these
_EXPLICIT_TOOL_METHODS: set[str] = {
    "smp/navigate",
    "smp/trace",
    "smp/context",
    "smp/impact",
    "smp/locate",
    "smp/search",
    "smp/flow",
    "smp/update",
    "smp/batch_update",
    "smp/reindex",
    "smp/enrich",
    "smp/enrich/batch",
    "smp/enrich/stale",
    "smp/enrich/status",
    "smp/annotate",
    "smp/annotate/bulk",
    "smp/tag",
    "smp/session/open",
    "smp/session/close",
    "smp/session/recover",
    "smp/dryrun",
    "smp/checkpoint",
    "smp/rollback",
    "smp/lock",
    "smp/unlock",
    "smp/audit/get",
    "smp/diff",
    "smp/plan",
    "smp/conflict",
    "smp/why",
    "smp/telemetry",
    "smp/review/create",
    "smp/review/approve",
    "smp/review/reject",
    "smp/sandbox/spawn",
    "smp/sandbox/execute",
    "smp/sandbox/kill",
    "smp/community/detect",
    "smp/community/list",
    "smp/community/get",
    "smp/community/boundaries",
    "smp/sync",
    "smp/index/import",
    "smp/integrity/check",
    "smp/integrity/baseline",
    "smp/vector/search",
    "smp/vector/upsert",
    "smp/vector/delete",
    "smp/pr/create",
}

# Auto-register any RPC methods not covered by explicit wrappers
for _method in sorted(_HANDLERS):
    if _method not in _EXPLICIT_TOOL_METHODS:
        _make_tool(_method)


# ---------------------------------------------------------------------------
# Graph intelligence tools (explicit wrappers for discoverability)
# ---------------------------------------------------------------------------


@mcp.tool(description="Search for entities and their relationships in the code graph")
async def smp_navigate(query: str, include_relationships: bool = True, ctx: Any = None) -> str:
    result = await _call_rpc("smp/navigate", {"query": query, "include_relationships": include_relationships}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Trace dependencies and references across the graph")
async def smp_trace(
    start: str, relationship: str = "CALLS", depth: int = 3, direction: str = "outgoing", ctx: Any = None
) -> str:
    result = await _call_rpc(
        "smp/trace", {"start": start, "relationship": relationship, "depth": depth, "direction": direction}, ctx
    )
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Extract surrounding context for a file")
async def smp_context(file_path: str, scope: str = "edit", depth: int = 2, ctx: Any = None) -> str:
    result = await _call_rpc("smp/context", {"file_path": file_path, "scope": scope, "depth": depth}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Assess the impact of changes to an entity")
async def smp_impact(entity: str, change_type: str = "delete", ctx: Any = None) -> str:
    result = await _call_rpc("smp/impact", {"entity": entity, "change_type": change_type}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Find specific code entities by description")
async def smp_locate(
    query: str,
    fields: list[str] | None = None,
    node_types: list[str] | None = None,
    top_k: int = 5,
    ctx: Any = None,
) -> str:
    result = await _call_rpc(
        "smp/locate",
        {
            "query": query,
            "fields": fields or ["name", "docstring", "tags"],
            "node_types": node_types or [],
            "top_k": top_k,
        },
        ctx,
    )
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Keyword search over names, docstrings, descriptions, and tags")
async def smp_search(query: str, match: str = "any", filter: str = "{}", top_k: int = 5, ctx: Any = None) -> str:
    filter_dict = _json.loads(filter) if isinstance(filter, str) else {}
    result = await _call_rpc("smp/search", {"query": query, "match": match, "filter": filter_dict, "top_k": top_k}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Find paths or flows between entities")
async def smp_flow(start: str, end: str, flow_type: str = "data", ctx: Any = None) -> str:
    result = await _call_rpc("smp/flow", {"start": start, "end": end, "flow_type": flow_type}, ctx)
    return _json.dumps(result, default=str, indent=2)


# ---------------------------------------------------------------------------
# Memory & Enrichment tools
# ---------------------------------------------------------------------------


@mcp.tool(description="Update or ingest a file into the graph")
async def smp_update(file_path: str, content: str = "", change_type: str = "modified", ctx: Any = None) -> str:
    result = await _call_rpc(
        "smp/update", {"file_path": file_path, "content": content, "change_type": change_type}, ctx
    )
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Apply multiple file updates in batch")
async def smp_batch_update(changes: str = "[]", ctx: Any = None) -> str:

    parsed = _json.loads(changes) if isinstance(changes, str) else changes
    result = await _call_rpc("smp/batch_update", {"changes": parsed}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Reindex the graph for a scope")
async def smp_reindex(scope: str = "full", ctx: Any = None) -> str:
    result = await _call_rpc("smp/reindex", {"scope": scope}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Mark a node as enriched")
async def smp_enrich(node_id: str, force: bool = False, ctx: Any = None) -> str:
    result = await _call_rpc("smp/enrich", {"node_id": node_id, "force": force}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Batch enrich multiple nodes within a scope")
async def smp_enrich_batch(scope: str = "full", force: bool = False, ctx: Any = None) -> str:
    result = await _call_rpc("smp/enrich/batch", {"scope": scope, "force": force}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Find stale enriched nodes whose source changed")
async def smp_enrich_stale(scope: str = "full", ctx: Any = None) -> str:
    result = await _call_rpc("smp/enrich/stale", {"scope": scope}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Check enrichment coverage status")
async def smp_enrich_status(scope: str = "full", ctx: Any = None) -> str:
    result = await _call_rpc("smp/enrich/status", {"scope": scope}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Manually annotate a node with description and tags")
async def smp_annotate(
    node_id: str, description: str = "", tags: str = "[]", force: bool = False, ctx: Any = None
) -> str:

    tag_list = _json.loads(tags) if isinstance(tags, str) else tags
    result = await _call_rpc(
        "smp/annotate", {"node_id": node_id, "description": description, "tags": tag_list, "force": force}, ctx
    )
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Bulk annotation of multiple nodes")
async def smp_annotate_bulk(annotations: str = "[]", ctx: Any = None) -> str:

    parsed = _json.loads(annotations) if isinstance(annotations, str) else annotations
    result = await _call_rpc("smp/annotate/bulk", {"annotations": parsed}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Add/remove/replace tags on nodes by scope")
async def smp_tag(scope: str = "", tags: str = "[]", action: str = "add", ctx: Any = None) -> str:

    tag_list = _json.loads(tags) if isinstance(tags, str) else tags
    result = await _call_rpc("smp/tag", {"scope": scope, "tags": tag_list, "action": action}, ctx)
    return _json.dumps(result, default=str, indent=2)


# ---------------------------------------------------------------------------
# Session & Safety tools
# ---------------------------------------------------------------------------


@mcp.tool(description="Open a safety session for tracking changes")
async def smp_session_open(
    agent_id: str = "", task: str = "", scope: str = "[]", mode: str = "read", ctx: Any = None
) -> str:

    scope_list = _json.loads(scope) if isinstance(scope, str) else scope
    result = await _call_rpc(
        "smp/session/open", {"agent_id": agent_id, "task": task, "scope": scope_list, "mode": mode}, ctx
    )
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Close an active session")
async def smp_session_close(session_id: str = "", status: str = "completed", ctx: Any = None) -> str:
    result = await _call_rpc("smp/session/close", {"session_id": session_id, "status": status}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Recover a session by ID")
async def smp_session_recover(session_id: str = "", ctx: Any = None) -> str:
    result = await _call_rpc("smp/session/recover", {"session_id": session_id}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Simulate a change and preview the diff")
async def smp_dryrun(
    session_id: str = "", file_path: str = "", proposed_content: str = "", change_summary: str = "", ctx: Any = None
) -> str:
    result = await _call_rpc(
        "smp/dryrun",
        {
            "session_id": session_id,
            "file_path": file_path,
            "proposed_content": proposed_content,
            "change_summary": change_summary,
        },
        ctx,
    )
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Create a recovery checkpoint")
async def smp_checkpoint(session_id: str = "", files: str = "[]", ctx: Any = None) -> str:

    file_list = _json.loads(files) if isinstance(files, str) else files
    result = await _call_rpc("smp/checkpoint", {"session_id": session_id, "files": file_list}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Rollback to a checkpoint")
async def smp_rollback(session_id: str = "", checkpoint_id: str = "", ctx: Any = None) -> str:
    result = await _call_rpc("smp/rollback", {"session_id": session_id, "checkpoint_id": checkpoint_id}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Lock files for exclusive access")
async def smp_lock(
    session_id: str = "", files: str = "[]", ttl_seconds: int = 300, force: bool = False, ctx: Any = None
) -> str:

    file_list = _json.loads(files) if isinstance(files, str) else files
    result = await _call_rpc(
        "smp/lock", {"session_id": session_id, "files": file_list, "ttl_seconds": ttl_seconds, "force": force}, ctx
    )
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Unlock files")
async def smp_unlock(session_id: str = "", files: str = "[]", ctx: Any = None) -> str:

    file_list = _json.loads(files) if isinstance(files, str) else files
    result = await _call_rpc("smp/unlock", {"session_id": session_id, "files": file_list}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Retrieve audit logs")
async def smp_audit_get(audit_log_id: str = "", ctx: Any = None) -> str:
    result = await _call_rpc("smp/audit/get", {"audit_log_id": audit_log_id}, ctx)
    return _json.dumps(result, default=str, indent=2)


# ---------------------------------------------------------------------------
# Analysis & Telemetry tools
# ---------------------------------------------------------------------------


@mcp.tool(description="Show diff between two snapshots")
async def smp_diff(from_snapshot: str = "", to_snapshot: str = "", scope: str = "full", ctx: Any = None) -> str:
    result = await _call_rpc(
        "smp/diff", {"from_snapshot": from_snapshot, "to_snapshot": to_snapshot, "scope": scope}, ctx
    )
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Generate a change plan for proposed modifications")
async def smp_plan(
    change_description: str = "",
    target_file: str = "",
    change_type: str = "refactor",
    scope: str = "full",
    ctx: Any = None,
) -> str:
    result = await _call_rpc(
        "smp/plan",
        {
            "change_description": change_description,
            "target_file": target_file,
            "change_type": change_type,
            "scope": scope,
        },
        ctx,
    )
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Check for conflicts in proposed changes")
async def smp_conflict(entity: str = "", proposed_change: str = "", context: str = "{}", ctx: Any = None) -> str:

    ctx_dict = _json.loads(context) if isinstance(context, str) else context
    result = await _call_rpc(
        "smp/conflict", {"entity": entity, "proposed_change": proposed_change, "context": ctx_dict}, ctx
    )
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Explain why relationships exist between entities")
async def smp_why(entity: str = "", relationship: str = "", depth: int = 3, ctx: Any = None) -> str:
    result = await _call_rpc("smp/why", {"entity": entity, "relationship": relationship, "depth": depth}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Query telemetry data about the graph")
async def smp_telemetry(
    action: str = "get_stats", node_id: str | None = None, threshold: int | None = None, ctx: Any = None
) -> str:
    result = await _call_rpc("smp/telemetry", {"action": action, "node_id": node_id, "threshold": threshold}, ctx)
    return _json.dumps(result, default=str, indent=2)


# ---------------------------------------------------------------------------
# Review & Handoff tools
# ---------------------------------------------------------------------------


@mcp.tool(description="Create a code review")
async def smp_review_create(
    session_id: str = "", files_changed: str = "[]", diff_summary: str = "", reviewers: str = "[]", ctx: Any = None
) -> str:

    result = await _call_rpc(
        "smp/review/create",
        {
            "session_id": session_id,
            "files_changed": _json.loads(files_changed) if isinstance(files_changed, str) else files_changed,
            "diff_summary": diff_summary,
            "reviewers": _json.loads(reviewers) if isinstance(reviewers, str) else reviewers,
        },
        ctx,
    )
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Approve a code review")
async def smp_review_approve(review_id: str = "", reviewer: str = "", ctx: Any = None) -> str:
    result = await _call_rpc("smp/review/approve", {"review_id": review_id, "reviewer": reviewer}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Reject a code review")
async def smp_review_reject(review_id: str = "", reviewer: str = "", reason: str = "", ctx: Any = None) -> str:
    result = await _call_rpc("smp/review/reject", {"review_id": review_id, "reviewer": reviewer, "reason": reason}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Create a pull request from a review")
async def smp_pr_create(
    review_id: str = "",
    title: str = "",
    body: str = "",
    branch: str = "",
    base_branch: str = "main",
    ctx: Any = None,
) -> str:
    result = await _call_rpc(
        "smp/pr/create",
        {"review_id": review_id, "title": title, "body": body, "branch": branch, "base_branch": base_branch},
        ctx,
    )
    return _json.dumps(result, default=str, indent=2)


# ---------------------------------------------------------------------------
# Sandbox tools
# ---------------------------------------------------------------------------


@mcp.tool(description="Spawn a new sandbox environment")
async def smp_sandbox_spawn(
    name: str | None = None, template: str | None = None, files: str = "{}", ctx: Any = None
) -> str:

    files_dict = _json.loads(files) if isinstance(files, str) else files
    result = await _call_rpc("smp/sandbox/spawn", {"name": name, "template": template, "files": files_dict}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Execute a command in a sandbox")
async def smp_sandbox_execute(
    sandbox_id: str = "", command: str = "[]", stdin: str | None = None, timeout: int | None = None, ctx: Any = None
) -> str:

    cmd_list = _json.loads(command) if isinstance(command, str) else command
    result = await _call_rpc(
        "smp/sandbox/execute", {"sandbox_id": sandbox_id, "command": cmd_list, "stdin": stdin, "timeout": timeout}, ctx
    )
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Kill a sandbox execution")
async def smp_sandbox_kill(execution_id: str = "", ctx: Any = None) -> str:
    result = await _call_rpc("smp/sandbox/kill", {"execution_id": execution_id}, ctx)
    return _json.dumps(result, default=str, indent=2)


# ---------------------------------------------------------------------------
# Community tools
# ---------------------------------------------------------------------------


@mcp.tool(description="Run community detection on the graph")
async def smp_community_detect(resolutions: str = "[]", relationship_types: str = "[]", ctx: Any = None) -> str:

    result = await _call_rpc(
        "smp/community/detect",
        {
            "resolutions": _json.loads(resolutions) if isinstance(resolutions, str) else resolutions,
            "relationship_types": _json.loads(relationship_types)
            if isinstance(relationship_types, str)
            else relationship_types,
        },
        ctx,
    )
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="List all communities in the graph")
async def smp_community_list(level: int | None = None, ctx: Any = None) -> str:
    result = await _call_rpc("smp/community/list", {"level": level}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Get all nodes in a specific community")
async def smp_community_get(
    community_id: str = "", node_types: str = "[]", include_bridges: bool = False, ctx: Any = None
) -> str:

    result = await _call_rpc(
        "smp/community/get",
        {
            "community_id": community_id,
            "node_types": _json.loads(node_types) if isinstance(node_types, str) else node_types,
            "include_bridges": include_bridges,
        },
        ctx,
    )
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Get coupling boundaries between communities")
async def smp_community_boundaries(level: int = 0, min_coupling: float = 0.05, ctx: Any = None) -> str:
    result = await _call_rpc("smp/community/boundaries", {"level": level, "min_coupling": min_coupling}, ctx)
    return _json.dumps(result, default=str, indent=2)


# ---------------------------------------------------------------------------
# Sync, Integrity & Vector tools
# ---------------------------------------------------------------------------


@mcp.tool(description="Sync with a remote graph snapshot")
async def smp_sync(remote_data: str = "{}", ctx: Any = None) -> str:

    parsed = _json.loads(remote_data) if isinstance(remote_data, str) else remote_data
    result = await _call_rpc("smp/sync", {"remote_data": parsed}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Bulk-import nodes and edges from serialised data")
async def smp_index_import(data: str = "{}", ctx: Any = None) -> str:

    parsed = _json.loads(data) if isinstance(data, str) else data
    result = await _call_rpc("smp/index/import", {"data": parsed}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Verify node integrity against a stored signature")
async def smp_integrity_check(node_id: str = "", current_state: str = "{}", ctx: Any = None) -> str:

    state = _json.loads(current_state) if isinstance(current_state, str) else current_state
    result = await _call_rpc("smp/integrity/check", {"node_id": node_id, "current_state": state}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Store a baseline signature for a node")
async def smp_integrity_baseline(node_id: str = "", state: str = "{}", ctx: Any = None) -> str:

    state_dict = _json.loads(state) if isinstance(state, str) else state
    result = await _call_rpc("smp/integrity/baseline", {"node_id": node_id, "state": state_dict}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Vector similarity search")
async def smp_vector_search(embedding: str = "[]", top_k: int = 5, where: str = "{}", ctx: Any = None) -> str:

    emb = _json.loads(embedding) if isinstance(embedding, str) else embedding
    wh = _json.loads(where) if isinstance(where, str) else where
    result = await _call_rpc("smp/vector/search", {"embedding": emb, "top_k": top_k, "where": wh}, ctx)
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Upsert vectors into the vector store")
async def smp_vector_upsert(
    ids: str = "[]", embeddings: str = "[]", metadatas: str = "[]", documents: str | None = None, ctx: Any = None
) -> str:

    result = await _call_rpc(
        "smp/vector/upsert",
        {
            "ids": _json.loads(ids) if isinstance(ids, str) else ids,
            "embeddings": _json.loads(embeddings) if isinstance(embeddings, str) else embeddings,
            "metadatas": _json.loads(metadatas) if isinstance(metadatas, str) else metadatas,
            "documents": _json.loads(documents) if isinstance(documents, str) else documents,
        },
        ctx,
    )
    return _json.dumps(result, default=str, indent=2)


@mcp.tool(description="Delete vectors by ID")
async def smp_vector_delete(ids: str = "[]", ctx: Any = None) -> str:

    id_list = _json.loads(ids) if isinstance(ids, str) else ids
    result = await _call_rpc("smp/vector/delete", {"ids": id_list}, ctx)
    return _json.dumps(result, default=str, indent=2)


# ---------------------------------------------------------------------------
# Resources (read-only endpoints)
# ---------------------------------------------------------------------------


@mcp.resource("smp://stats", description="System statistics")
async def stats_resource() -> str:
    if _state.graph is None:
        return _json.dumps({"error": "graph not available"})
    try:
        nodes = await _state.graph.count_nodes()
        edges = await _state.graph.count_edges()
        return _json.dumps({"nodes": nodes, "edges": edges}, indent=2)
    except Exception as exc:  # noqa: BLE001
        return _json.dumps({"error": str(exc)[:200]})


@mcp.resource("smp://health", description="Health status")
async def health_resource() -> str:
    if _state.graph is None:
        return _json.dumps({"status": "unavailable", "error": "graph not available"})
    try:
        await _state.graph.count_nodes()
        return _json.dumps({"status": "healthy"})
    except Exception as exc:  # noqa: BLE001
        return _json.dumps({"status": "unhealthy", "error": str(exc)[:200]})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP server over stdio (for Claude Desktop etc.)."""
    mcp.run()


if __name__ == "__main__":
    main()
