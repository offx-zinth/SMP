from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

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

# Load environment variables from .env file
load_dotenv()

log = get_logger(__name__)


@asynccontextmanager
async def app_lifespan(app: Any = None) -> AsyncGenerator[dict[str, Any], None]:
    """Manage resources that live for the server's lifetime."""
    uri = os.environ.get("SMP_NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("SMP_NEO4J_USER", "neo4j")
    password = os.environ.get("SMP_NEO4J_PASSWORD", "")

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

    safety_enabled = os.environ.get("SMP_SAFETY_ENABLED", "false").lower() == "true"
    safety: dict[str, Any] | None = None
    telemetry_engine = None
    handoff_manager = None
    integrity_verifier = None

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

    log.info("mcp_server_started", neo4j=uri, safety=safety_enabled)
    yield state

    await graph.close()
    log.info("mcp_server_stopped")


# Initialize the MCP server
mcp = FastMCP("smp_mcp", lifespan=app_lifespan)


async def _call_rpc(method: str, params: dict[str, Any], state: dict[str, Any]) -> Any:
    """Helper to route MCP tool calls to the SMP dispatcher."""
    dispatcher = get_dispatcher()
    handler = dispatcher.get_handler(method)
    if not handler:
        raise ValueError(f"Method not found: {method}")

    # Map state to context expected by handlers
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

    return await handler.handle(params, context)


# --- Graph Intelligence Tools ---


class NavigateInput(BaseModel):
    """Input for navigating the structural graph."""

    query: str = Field(..., description="Search query to find the starting point in the graph")
    include_relationships: bool = Field(True, description="Whether to include relationships in the result")


@mcp.tool(name="smp_navigate", annotations={"title": "Navigate Graph", "readOnlyHint": True})
async def smp_navigate(params: NavigateInput, ctx: Any) -> Any:
    """Navigate the structural graph to find entities and their relationships.

    Args:
        params (NavigateInput): Navigation parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/navigate", params.model_dump(), state)


class TraceInput(BaseModel):
    """Input for tracing entity dependencies."""

    start: str = Field(..., description="Starting entity ID or name")
    relationship: str = Field(
        "CALLS", description="Relationship type to trace (e.g., 'CALLS', 'DEFINES', 'DEPENDS_ON')"
    )
    depth: int = Field(3, description="Maximum depth of the trace", ge=1, le=10)
    direction: str = Field("outgoing", description="Direction of the trace ('outgoing' or 'incoming')")


@mcp.tool(name="smp_trace", annotations={"title": "Trace Dependencies", "readOnlyHint": True})
async def smp_trace(params: TraceInput, ctx: Any) -> Any:
    """Trace dependencies or references of an entity across the graph.

    Args:
        params (TraceInput): Trace parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/trace", params.model_dump(), state)


class ContextInput(BaseModel):
    """Input for extracting local context of a file."""

    file_path: str = Field(..., description="Path to the source file")
    scope: str = Field("edit", description="Context scope ('edit', 'read', 'full')")
    depth: int = Field(2, description="Depth of context extraction", ge=1, le=5)


@mcp.tool(name="smp_context", annotations={"title": "Get Local Context", "readOnlyHint": True})
async def smp_context(params: ContextInput, ctx: Any) -> Any:
    """Extract the surrounding structural and semantic context for a given file.

    Args:
        params (ContextInput): Context parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/context", params.model_dump(), state)


class ImpactInput(BaseModel):
    """Input for assessing the impact of a change."""

    entity: str = Field(..., description="Entity ID or name to analyze")
    change_type: str = Field("delete", description="Type of change ('delete', 'modify', 'add')")


@mcp.tool(name="smp_impact", annotations={"title": "Assess Impact", "readOnlyHint": True})
async def smp_impact(params: ImpactInput, ctx: Any) -> Any:
    """Assess the potential impact of changing or deleting a code entity.

    Args:
        params (ImpactInput): Impact analysis parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/impact", params.model_dump(), state)


class LocateInput(BaseModel):
    """Input for locating specific entities."""

    query: str = Field(..., description="Query to locate entities")
    fields: list[str] = Field(default=["name", "docstring", "tags"], description="Fields to return for each entity")
    node_types: list[str] = Field(
        default_factory=list, description="Filter by entity types (e.g., 'Function', 'Class')"
    )
    top_k: int = Field(5, description="Maximum number of results", ge=1, le=50)


@mcp.tool(name="smp_locate", annotations={"title": "Locate Entities", "readOnlyHint": True})
async def smp_locate(params: LocateInput, ctx: Any) -> Any:
    """Locate specific code entities based on names, types, or properties.

    Args:
        params (LocateInput): Location parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/locate", params.model_dump(), state)


class SearchInput(BaseModel):
    """Input for semantic search."""

    query: str = Field(..., description="Semantic search query")
    match: str = Field("any", description="Match strategy ('any', 'all', 'exact')")
    filter: dict[str, Any] = Field(default_factory=dict, description="Additional filters")
    top_k: int = Field(5, description="Maximum number of results", ge=1, le=50)


@mcp.tool(name="smp_search", annotations={"title": "Semantic Search", "readOnlyHint": True})
async def smp_search(params: SearchInput, ctx: Any) -> Any:
    """Perform a semantic search across the codebase using vector embeddings.

    Args:
        params (SearchInput): Search parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/search", params.model_dump(), state)


class FlowInput(BaseModel):
    """Input for finding flows between entities."""

    start: str = Field(..., description="Starting entity ID or name")
    end: str = Field(..., description="Ending entity ID or name")
    flow_type: str = Field("data", description="Type of flow to find ('data', 'control', 'dependency')")


@mcp.tool(name="smp_flow", annotations={"title": "Find Flow", "readOnlyHint": True})
async def smp_flow(params: FlowInput, ctx: Any) -> Any:
    """Find the path or flow between two entities in the graph.

    Args:
        params (FlowInput): Flow parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/flow", params.model_dump(), state)


class WhyInput(BaseModel):
    """Input for explaining graph relationships."""

    entity: str = Field(..., description="Entity ID or name")
    relationship: str = Field("", description="The relationship to explain")
    depth: int = Field(3, description="Depth of explanation", ge=1, le=5)


@mcp.tool(name="smp_why", annotations={"title": "Explain Relationship", "readOnlyHint": True})
async def smp_why(params: WhyInput, ctx: Any) -> Any:
    """Explain why a specific relationship exists between entities in the graph.

    Args:
        params (WhyInput): Explanation parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/graph/why", params.model_dump(), state)


# --- Memory & Enrichment Tools ---


class UpdateInput(BaseModel):
    """Input for updating a file in the structural graph."""

    file_path: str = Field(..., description="Path to the file to update")
    content: str = Field("", description="New content of the file. If empty, the file will be parsed from disk")
    change_type: str = Field("modified", description="Type of change ('modified', 'added', 'deleted')")
    language: str | None = Field(None, description="Language of the file. If not specified, auto-detected from file extension")


@mcp.tool(name="smp_update", annotations={"title": "Update File", "destructiveHint": True})
async def smp_update(params: UpdateInput, ctx: Any) -> Any:
    """Update or ingest a file into the structural graph.

    Args:
        params (UpdateInput): Update parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/update", params.model_dump(), state)


class BatchUpdateInput(BaseModel):
    """Input for updating multiple files."""

    changes: list[dict[str, str]] = Field(default_factory=list, description="List of file changes to apply")


@mcp.tool(name="smp_batch_update", annotations={"title": "Batch Update Files", "destructiveHint": True})
async def smp_batch_update(params: BatchUpdateInput, ctx: Any) -> Any:
    """Apply multiple file updates to the structural graph in a single request.

    Args:
        params (BatchUpdateInput): Batch update parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/batch_update", params.model_dump(), state)


class ReindexInput(BaseModel):
    """Input for reindexing the graph."""

    scope: str = Field("full", description="Scope of reindexing ('full', 'partial')")


@mcp.tool(name="smp_reindex", annotations={"title": "Reindex Graph", "destructiveHint": True})
async def smp_reindex(params: ReindexInput, ctx: Any) -> Any:
    """Request a reindexing of the structural graph and vector store.

    Args:
        params (ReindexInput): Reindex parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/reindex", params.model_dump(), state)


class EnrichInput(BaseModel):
    """Input for enriching a specific node."""

    node_id: str = Field(..., description="ID of the node to enrich")
    force: bool = Field(False, description="Force re-enrichment even if already enriched")


@mcp.tool(name="smp_enrich", annotations={"title": "Enrich Node", "destructiveHint": True})
async def smp_enrich(params: EnrichInput, ctx: Any) -> Any:
    """Enrich a specific graph node with semantic metadata using an LLM.

    Args:
        params (EnrichInput): Enrichment parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/enrich", params.model_dump(), state)


class EnrichBatchInput(BaseModel):
    """Input for batch enrichment."""

    scope: str = Field("full", description="Scope of nodes to enrich ('full', 'stale', 'custom')")
    force: bool = Field(False, description="Force re-enrichment")


@mcp.tool(name="smp_enrich_batch", annotations={"title": "Batch Enrich Nodes", "destructiveHint": True})
async def smp_enrich_batch(params: EnrichBatchInput, ctx: Any) -> Any:
    """Enrich multiple nodes in the graph based on a specified scope.

    Args:
        params (EnrichBatchInput): Batch enrichment parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/enrich/batch", params.model_dump(), state)


class EnrichStaleInput(BaseModel):
    """Input for identifying stale enriched nodes."""

    scope: str = Field("full", description="Scope to check for stale nodes")


@mcp.tool(name="smp_enrich_stale", annotations={"title": "Find Stale Enrichment", "readOnlyHint": True})
async def smp_enrich_stale(params: EnrichStaleInput, ctx: Any) -> Any:
    """Identify nodes whose source code has changed since they were last enriched.

    Args:
        params (EnrichStaleInput): Stale check parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/enrich/stale", params.model_dump(), state)


class EnrichStatusInput(BaseModel):
    """Input for checking enrichment status."""

    scope: str = Field("full", description="Scope to check enrichment status")


@mcp.tool(name="smp_enrich_status", annotations={"title": "Enrichment Status", "readOnlyHint": True})
async def smp_enrich_status(params: EnrichStatusInput, ctx: Any) -> Any:
    """Get statistics about the enrichment coverage of the graph.

    Args:
        params (EnrichStatusInput): Status parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/enrich/status", params.model_dump(), state)


class AnnotateInput(BaseModel):
    """Input for manually annotating a node."""

    node_id: str = Field(..., description="ID of the node to annotate")
    description: str = Field("", description="Manual description for the entity")
    tags: list[str] = Field(default_factory=list, description="Tags to associate with the entity")
    force: bool = Field(False, description="Force override existing extracted docstring")


@mcp.tool(name="smp_annotate", annotations={"title": "Annotate Node", "destructiveHint": True})
async def smp_annotate(params: AnnotateInput, ctx: Any) -> Any:
    """Manually set a description or tags for a graph node.

    Args:
        params (AnnotateInput): Annotation parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/annotate", params.model_dump(), state)


class AnnotateBulkInput(BaseModel):
    """Input for bulk annotation."""

    annotations: list[dict[str, Any]] = Field(default_factory=list, description="List of annotations to apply")


@mcp.tool(name="smp_annotate_bulk", annotations={"title": "Bulk Annotate Nodes", "destructiveHint": True})
async def smp_annotate_bulk(params: AnnotateBulkInput, ctx: Any) -> Any:
    """Apply multiple manual annotations to the graph in a single request.

    Args:
        params (AnnotateBulkInput): Bulk annotation parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/annotate/bulk", params.model_dump(), state)


class TagInput(BaseModel):
    """Input for tagging entities in a scope."""

    scope: str = Field("", description="Scope of nodes to tag")
    tags: list[str] = Field(default_factory=list, description="Tags to add/remove/replace")
    action: str = Field("add", description="Action to perform ('add', 'remove', 'replace')")


@mcp.tool(name="smp_tag", annotations={"title": "Tag Entities", "destructiveHint": True})
async def smp_tag(params: TagInput, ctx: Any) -> Any:
    """Add, remove, or replace tags for all entities within a given scope.

    Args:
        params (TagInput): Tagging parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/tag", params.model_dump(), state)


# --- Safety & Integrity Tools ---


class SessionOpenInput(BaseModel):
    """Input for opening a safety session."""

    agent_id: str = Field("", description="ID of the agent performing the task")
    task: str = Field("", description="Description of the task")
    scope: list[str] = Field(default_factory=list, description="Scope of the session (files, modules)")
    mode: str = Field("read", description="Session mode ('read', 'write', 'admin')")


@mcp.tool(name="smp_session_open", annotations={"title": "Open Session", "destructiveHint": False})
async def smp_session_open(params: SessionOpenInput, ctx: Any) -> Any:
    """Open a safety session to track changes and enforce guards.

    Args:
        params (SessionOpenInput): Session open parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/session/open", params.model_dump(), state)


class SessionCloseInput(BaseModel):
    """Input for closing a safety session."""

    session_id: str = Field(..., description="ID of the session to close")
    status: str = Field("completed", description="Final status of the session ('completed', 'failed', 'cancelled')")


@mcp.tool(name="smp_session_close", annotations={"title": "Close Session", "destructiveHint": False})
async def smp_session_close(params: SessionCloseInput, ctx: Any) -> Any:
    """Close a safety session and finalize audit logs.

    Args:
        params (SessionCloseInput): Session close parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/session/close", params.model_dump(), state)


class GuardCheckInput(BaseModel):
    """Input for checking a proposed change against guards."""

    session_id: str = Field(..., description="Active session ID")
    target: str = Field(..., description="Entity or file being targeted")
    intended_change: str = Field(..., description="Description of the intended change")


@mcp.tool(name="smp_guard_check", annotations={"title": "Guard Check", "readOnlyHint": True})
async def smp_guard_check(params: GuardCheckInput, ctx: Any) -> Any:
    """Check if a proposed change violates any safety guards.

    Args:
        params (GuardCheckInput): Guard check parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/guard/check", params.model_dump(), state)


class DryRunInput(BaseModel):
    """Input for simulating a change."""

    session_id: str = Field(..., description="Active session ID")
    file_path: str = Field(..., description="Path to the file to modify")
    proposed_content: str = Field(..., description="The new content for the file")
    change_summary: str = Field(..., description="Summary of the change")


@mcp.tool(name="smp_dryrun", annotations={"title": "Dry Run", "readOnlyHint": True})
async def smp_dryrun(params: DryRunInput, ctx: Any) -> Any:
    """Simulate a change to see its effect without actually applying it.

    Args:
        params (DryRunInput): Dry run parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/dryrun", params.model_dump(), state)


class CheckpointInput(BaseModel):
    """Input for creating a checkpoint."""

    session_id: str = Field(..., description="Active session ID")
    files: list[str] = Field(default_factory=list, description="Files to include in the checkpoint")


@mcp.tool(name="smp_checkpoint", annotations={"title": "Create Checkpoint", "destructiveHint": True})
async def smp_checkpoint(params: CheckpointInput, ctx: Any) -> Any:
    """Create a recovery checkpoint for the current state of files.

    Args:
        params (CheckpointInput): Checkpoint parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/checkpoint", params.model_dump(), state)


class RollbackInput(BaseModel):
    """Input for rolling back to a checkpoint."""

    session_id: str = Field(..., description="Active session ID")
    checkpoint_id: str = Field(..., description="ID of the checkpoint to restore")


@mcp.tool(name="smp_rollback", annotations={"title": "Rollback", "destructiveHint": True})
async def smp_rollback(params: RollbackInput, ctx: Any) -> Any:
    """Restore files to the state they were in at a specific checkpoint.

    Args:
        params (RollbackInput): Rollback parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/rollback", params.model_dump(), state)


class LockInput(BaseModel):
    """Input for locking/unlocking files."""

    session_id: str = Field(..., description="Active session ID")
    files: list[str] = Field(default_factory=list, description="Files to lock/unlock")


@mcp.tool(name="smp_lock", annotations={"title": "Lock Files", "destructiveHint": False})
async def smp_lock(params: LockInput, ctx: Any) -> Any:
    """Acquire locks on specific files to prevent concurrent modifications.

    Args:
        params (LockInput): Lock parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/lock", params.model_dump(), state)


@mcp.tool(name="smp_unlock", annotations={"title": "Unlock Files", "destructiveHint": False})
async def smp_unlock(params: LockInput, ctx: Any) -> Any:
    """Release locks on specific files.

    Args:
        params (LockInput): Unlock parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/unlock", params.model_dump(), state)


class AuditGetInput(BaseModel):
    """Input for retrieving audit logs."""

    audit_log_id: str = Field(..., description="ID of the audit log to retrieve")


@mcp.tool(name="smp_audit_get", annotations={"title": "Get Audit Log", "readOnlyHint": True})
async def smp_audit_get(params: AuditGetInput, ctx: Any) -> Any:
    """Retrieve the audit log for a specific session or operation.

    Args:
        params (AuditGetInput): Audit log parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/audit/get", params.model_dump(), state)


class IntegrityCheckInput(BaseModel):
    """Input for verifying node integrity."""

    node_id: str = Field(..., description="ID of the node to verify")
    current_state: dict[str, Any] = Field(default_factory=dict, description="Current state of the node for comparison")


@mcp.tool(name="smp_verify_integrity", annotations={"title": "Verify Integrity", "readOnlyHint": True})
async def smp_verify_integrity(params: IntegrityCheckInput, ctx: Any) -> Any:
    """Verify that a graph node's state is consistent and untampered.

    Args:
        params (IntegrityCheckInput): Integrity check parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/verify/integrity", params.model_dump(), state)


# --- Execution & Sandbox Tools ---


class SandboxSpawnInput(BaseModel):
    """Input for spawning a sandbox."""

    name: str | None = Field(None, description="Optional name for the sandbox")
    template: str | None = Field(None, description="Template to use for the sandbox")
    files: dict[str, str] = Field(default_factory=dict, description="Files to initialize in the sandbox")


@mcp.tool(name="smp_sandbox_spawn", annotations={"title": "Spawn Sandbox", "destructiveHint": True})
async def smp_sandbox_spawn(params: SandboxSpawnInput, ctx: Any) -> Any:
    """Create a new isolated sandbox environment for safe execution.

    Args:
        params (SandboxSpawnInput): Sandbox spawn parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/sandbox/spawn", params.model_dump(), state)


class SandboxExecuteInput(BaseModel):
    """Input for executing commands in a sandbox."""

    command: list[str] = Field(default_factory=list, description="Command to execute (as a list of arguments)")
    stdin: str | None = Field(None, description="Standard input to provide to the command")
    working_directory: str | None = Field(None, description="Working directory for the command")


@mcp.tool(name="smp_sandbox_execute", annotations={"title": "Execute in Sandbox", "destructiveHint": True})
async def smp_sandbox_execute(params: SandboxExecuteInput, ctx: Any) -> Any:
    """Execute a command or script within a sandbox environment.

    Args:
        params (SandboxExecuteInput): Execution parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/sandbox/execute", params.model_dump(), state)


class SandboxDestroyInput(BaseModel):
    """Input for destroying a sandbox."""

    sandbox_id: str = Field(..., description="ID of the sandbox to destroy")


@mcp.tool(name="smp_sandbox_destroy", annotations={"title": "Destroy Sandbox", "destructiveHint": True})
async def smp_sandbox_destroy(params: SandboxDestroyInput, ctx: Any) -> Any:
    """Destroy a sandbox and free its resources.

    Args:
        params (SandboxDestroyInput): Sandbox destroy parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/sandbox/destroy", params.model_dump(), state)


# --- Coordination & Observability Tools ---


class ReviewCreateInput(BaseModel):
    """Input for creating a code review."""

    session_id: str = Field("", description="Active session ID")
    files_changed: list[str] = Field(default_factory=list, description="List of files that were changed")
    diff_summary: str = Field("", description="Summary of the changes")
    reviewers: list[str] = Field(default_factory=list, description="List of reviewer IDs or names")


@mcp.tool(name="smp_handoff_review", annotations={"title": "Create Code Review", "destructiveHint": False})
async def smp_handoff_review(params: ReviewCreateInput, ctx: Any) -> Any:
    """Create a code review for handoff to human reviewers.

    Args:
        params (ReviewCreateInput): Review creation parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/handoff/review", params.model_dump(), state)


class ReviewApproveInput(BaseModel):
    """Input for approving a code review."""

    review_id: str = Field(..., description="ID of the review to approve")
    reviewer: str = Field(..., description="Name or ID of the reviewer")


@mcp.tool(name="smp_handoff_approve", annotations={"title": "Approve Review", "destructiveHint": False})
async def smp_handoff_approve(params: ReviewApproveInput, ctx: Any) -> Any:
    """Approve a code review.

    Args:
        params (ReviewApproveInput): Approval parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/handoff/review/approve", params.model_dump(), state)


class ReviewRejectInput(BaseModel):
    """Input for rejecting a code review."""

    review_id: str = Field(..., description="ID of the review to reject")
    reviewer: str = Field(..., description="Name or ID of the reviewer")
    reason: str = Field(..., description="Reason for rejection")


@mcp.tool(name="smp_handoff_reject", annotations={"title": "Reject Review", "destructiveHint": False})
async def smp_handoff_reject(params: ReviewRejectInput, ctx: Any) -> Any:
    """Reject a code review with feedback.

    Args:
        params (ReviewRejectInput): Rejection parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/handoff/review/reject", params.model_dump(), state)


class PRCreateInput(BaseModel):
    """Input for creating a pull request."""

    review_id: str = Field(..., description="ID of the approved review")
    title: str = Field(..., description="Title for the pull request")
    body: str = Field(..., description="Description/body of the pull request")
    branch: str = Field(..., description="Branch name for the changes")
    base_branch: str = Field("main", description="Base branch to merge into")


@mcp.tool(name="smp_handoff_pr", annotations={"title": "Create Pull Request", "destructiveHint": True})
async def smp_handoff_pr(params: PRCreateInput, ctx: Any) -> Any:
    """Create a pull request from an approved code review.

    Args:
        params (PRCreateInput): Pull request creation parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/handoff/pr", params.model_dump(), state)


class TelemetryInput(BaseModel):
    """Input for telemetry operations."""

    action: str = Field("get_stats", description="Telemetry action ('get_stats', 'get_hot', 'decay')")
    node_id: str | None = Field(None, description="Optional node ID for specific queries")
    threshold: int | None = Field(None, description="Optional threshold for hot path detection")


@mcp.tool(name="smp_telemetry", annotations={"title": "Telemetry", "readOnlyHint": True})
async def smp_telemetry(params: TelemetryInput, ctx: Any) -> Any:
    """Query telemetry data about execution patterns and hot paths.

    Args:
        params (TelemetryInput): Telemetry parameters.
    """
    state = ctx.request_context.lifespan_state
    return await _call_rpc("smp/telemetry", params.model_dump(), state)


# --- System Resources ---


@mcp.resource("smp://stats")
async def get_stats() -> str:
    """Get system statistics about the graph (read-only)."""
    import json

    # This would be populated from the state in a real implementation
    stats = {"nodes": "Use smp_navigate to query nodes", "edges": "Use smp_trace to explore edges", "status": "online"}
    return json.dumps(stats, indent=2)


@mcp.resource("smp://health")
async def get_health() -> str:
    """Get health status of the MCP server."""
    import json

    health = {"status": "healthy", "service": "smp_mcp", "version": "3.0.0"}
    return json.dumps(health, indent=2)


if __name__ == "__main__":
    mcp.run()
