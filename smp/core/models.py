"""Core data models for SMP(3).

Partitioned schema: structural vs semantic properties.
All models use msgspec.Struct for zero-cost serialization and validation.
"""

from __future__ import annotations

import enum
from typing import Any

import msgspec

# ---------------------------------------------------------------------------
# Enumerations (SMP(3) schema)
# ---------------------------------------------------------------------------


class NodeType(enum.StrEnum):
    """Node types per SMP(3) specification."""

    REPOSITORY = "Repository"
    PACKAGE = "Package"
    FILE = "File"
    CLASS = "Class"
    FUNCTION = "Function"
    VARIABLE = "Variable"
    INTERFACE = "Interface"
    TEST = "Test"
    CONFIG = "Config"


class EdgeType(enum.StrEnum):
    """Relationship types per SMP(3) specification."""

    CONTAINS = "CONTAINS"
    IMPORTS = "IMPORTS"
    DEFINES = "DEFINES"
    CALLS = "CALLS"
    CALLS_RUNTIME = "CALLS_RUNTIME"
    INHERITS = "INHERITS"
    IMPLEMENTS = "IMPLEMENTS"
    DEPENDS_ON = "DEPENDS_ON"
    TESTS = "TESTS"
    USES = "USES"
    REFERENCES = "REFERENCES"


class Language(enum.StrEnum):
    """Supported source languages."""

    PYTHON = "python"
    TYPESCRIPT = "typescript"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Structural properties (coordinates, signature, complexity)
# ---------------------------------------------------------------------------


class StructuralProperties(msgspec.Struct, frozen=True):
    """Immutable structural coordinates of a code entity."""

    name: str = ""
    file: str = ""
    signature: str = ""
    start_line: int = 0
    end_line: int = 0
    complexity: int = 0
    lines: int = 0
    parameters: int = 0


# ---------------------------------------------------------------------------
# Semantic properties (docstrings, comments, decorators, annotations, tags)
# ---------------------------------------------------------------------------


class InlineComment(msgspec.Struct, frozen=True):
    """A single inline comment extracted from source."""

    line: int = 0
    text: str = ""


class Annotations(msgspec.Struct, frozen=True):
    """Structured type annotations extracted from a function/method."""

    params: dict[str, str] = msgspec.field(default_factory=dict)
    returns: str | None = None
    throws: list[str] = msgspec.field(default_factory=list)


class SemanticProperties(msgspec.Struct):
    """Mutable semantic metadata extracted via static AST analysis."""

    status: str = "no_metadata"
    docstring: str = ""
    description: str | None = None
    inline_comments: list[InlineComment] = msgspec.field(default_factory=list)
    decorators: list[str] = msgspec.field(default_factory=list)
    annotations: Annotations | None = None
    tags: list[str] = msgspec.field(default_factory=list)
    manually_set: bool = False
    source_hash: str = ""
    enriched_at: str = ""


# ---------------------------------------------------------------------------
# Graph primitives
# ---------------------------------------------------------------------------


class GraphNode(msgspec.Struct):
    """A single node in the structural graph with partitioned properties."""

    id: str
    type: NodeType
    file_path: str
    structural: StructuralProperties = msgspec.field(default_factory=StructuralProperties)
    semantic: SemanticProperties = msgspec.field(default_factory=SemanticProperties)

    def fingerprint(self) -> str:
        """Deterministic identity key for deduplication."""
        return f"{self.file_path}::{self.type.value}::{self.structural.name}::{self.structural.start_line}"


class GraphEdge(msgspec.Struct):
    """A directed edge between two nodes."""

    source_id: str
    target_id: str
    type: EdgeType
    metadata: dict[str, str] = msgspec.field(default_factory=dict)


# ---------------------------------------------------------------------------
# Document — the unit of parsing
# ---------------------------------------------------------------------------


class ParseError(msgspec.Struct):
    """Non-fatal error encountered during parsing."""

    message: str
    line: int = 0
    column: int = 0
    severity: str = "error"


class Document(msgspec.Struct):
    """A parsed source file with its extracted graph elements."""

    file_path: str
    language: Language = Language.UNKNOWN
    content_hash: str = ""
    nodes: list[GraphNode] = msgspec.field(default_factory=list)
    edges: list[GraphEdge] = msgspec.field(default_factory=list)
    errors: list[ParseError] = msgspec.field(default_factory=list)


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 protocol models
# ---------------------------------------------------------------------------


class JsonRpcRequest(msgspec.Struct):
    """JSON-RPC 2.0 request envelope."""

    jsonrpc: str = "2.0"
    method: str = ""
    params: dict[str, Any] = msgspec.field(default_factory=dict)
    id: int | str | None = None


class JsonRpcError(msgspec.Struct):
    """JSON-RPC 2.0 error object."""

    code: int
    message: str
    data: Any = None


class JsonRpcResponse(msgspec.Struct):
    """JSON-RPC 2.0 response envelope."""

    jsonrpc: str = "2.0"
    result: Any = None
    error: JsonRpcError | None = None
    id: int | str | None = None


# ---------------------------------------------------------------------------
# Memory Management params
# ---------------------------------------------------------------------------


class UpdateParams(msgspec.Struct):
    """Parameters for smp/update."""

    file_path: str
    content: str = ""
    change_type: str = "modified"
    language: Language = Language.PYTHON


class BatchUpdateParams(msgspec.Struct):
    """Parameters for smp/batch_update."""

    changes: list[dict[str, str]] = msgspec.field(default_factory=list)


class ReindexParams(msgspec.Struct):
    """Parameters for smp/reindex."""

    scope: str = "full"


# ---------------------------------------------------------------------------
# Enrichment params
# ---------------------------------------------------------------------------


class EnrichParams(msgspec.Struct):
    """Parameters for smp/enrich."""

    node_id: str
    force: bool = False


class EnrichBatchParams(msgspec.Struct):
    """Parameters for smp/enrich/batch."""

    scope: str = "full"
    force: bool = False


class EnrichStaleParams(msgspec.Struct):
    """Parameters for smp/enrich/stale."""

    scope: str = "full"


class EnrichStatusParams(msgspec.Struct):
    """Parameters for smp/enrich/status."""

    scope: str = "full"


# ---------------------------------------------------------------------------
# Annotation params
# ---------------------------------------------------------------------------


class AnnotateParams(msgspec.Struct):
    """Parameters for smp/annotate."""

    node_id: str
    description: str = ""
    tags: list[str] = msgspec.field(default_factory=list)
    force: bool = False


class AnnotateBulkItem(msgspec.Struct):
    """Single annotation in a bulk request."""

    node_id: str
    description: str = ""
    tags: list[str] = msgspec.field(default_factory=list)


class AnnotateBulkParams(msgspec.Struct):
    """Parameters for smp/annotate/bulk."""

    annotations: list[AnnotateBulkItem] = msgspec.field(default_factory=list)


class TagParams(msgspec.Struct):
    """Parameters for smp/tag."""

    scope: str = ""
    tags: list[str] = msgspec.field(default_factory=list)
    action: str = "add"


# ---------------------------------------------------------------------------
# Session / Safety params
# ---------------------------------------------------------------------------


class SessionOpenParams(msgspec.Struct):
    """Parameters for smp/session/open."""

    agent_id: str = ""
    task: str = ""
    scope: list[str] = msgspec.field(default_factory=list)
    mode: str = "read"


class SessionCloseParams(msgspec.Struct):
    """Parameters for smp/session/close."""

    session_id: str = ""
    status: str = "completed"


class SessionRecoverParams(msgspec.Struct):
    """Parameters for smp/session/recover."""

    session_id: str = ""


class GuardCheckParams(msgspec.Struct):
    target: str = ""
    intended_change: str = ""


class DryRunParams(msgspec.Struct):
    """Parameters for smp/dryrun."""

    session_id: str = ""
    file_path: str = ""
    proposed_content: str = ""
    change_summary: str = ""


class CheckpointParams(msgspec.Struct):
    """Parameters for smp/checkpoint."""

    session_id: str = ""
    files: list[str] = msgspec.field(default_factory=list)


class RollbackParams(msgspec.Struct):
    """Parameters for smp/rollback."""

    session_id: str = ""
    checkpoint_id: str = ""


class LockParams(msgspec.Struct):
    """Parameters for smp/lock and smp/unlock."""

    session_id: str = ""
    files: list[str] = msgspec.field(default_factory=list)


class AuditGetParams(msgspec.Struct):
    """Parameters for smp/audit/get."""

    audit_log_id: str = ""


# ---------------------------------------------------------------------------
# Query params
# ---------------------------------------------------------------------------


class NavigateParams(msgspec.Struct):
    """Parameters for smp/navigate."""

    query: str = ""
    include_relationships: bool = True


class TraceParams(msgspec.Struct):
    """Parameters for smp/trace."""

    start: str = ""
    relationship: str = "CALLS"
    depth: int = 3
    direction: str = "outgoing"


class ContextParams(msgspec.Struct):
    """Parameters for smp/context."""

    file_path: str = ""
    scope: str = "edit"
    depth: int = 2


class ImpactParams(msgspec.Struct):
    """Parameters for smp/impact."""

    entity: str = ""
    change_type: str = "delete"


class LocateParams(msgspec.Struct):
    """Parameters for smp/locate."""

    query: str = ""
    fields: list[str] = msgspec.field(default_factory=lambda: ["name", "docstring", "tags"])
    node_types: list[str] = msgspec.field(default_factory=list)
    top_k: int = 5


class SearchParams(msgspec.Struct):
    """Parameters for smp/search."""

    query: str = ""
    match: str = "any"
    filter: dict[str, Any] = msgspec.field(default_factory=dict)
    top_k: int = 5


class FlowParams(msgspec.Struct):
    """Parameters for smp/flow."""

    start: str = ""
    end: str = ""
    flow_type: str = "data"


# ---------------------------------------------------------------------------
# SMP(3) Runtime Models
# ---------------------------------------------------------------------------


class RuntimeEdge(msgspec.Struct):
    """Runtime edge tracking actual execution paths."""

    source_id: str = ""
    target_id: str = ""
    edge_type: str = "CALLS_RUNTIME"
    timestamp: str = ""
    session_id: str = ""
    trace_id: str = ""
    duration_ms: int = 0
    metadata: dict[str, Any] = msgspec.field(default_factory=dict)


class RuntimeTrace(msgspec.Struct):
    """Complete runtime trace for a session."""

    trace_id: str = ""
    session_id: str = ""
    agent_id: str = ""
    started_at: str = ""
    ended_at: str = ""
    edges: list[RuntimeEdge] = msgspec.field(default_factory=list)
    nodes_visited: list[str] = msgspec.field(default_factory=list)


# ---------------------------------------------------------------------------
# SMP(3) Additional Query Params
# ---------------------------------------------------------------------------


class DiffParams(msgspec.Struct):
    """Parameters for smp/diff."""

    from_snapshot: str = ""
    to_snapshot: str = ""
    scope: str = "full"


class PlanParams(msgspec.Struct):
    """Parameters for smp/plan."""

    change_description: str = ""
    target_file: str = ""
    change_type: str = "refactor"
    scope: str = "full"


class ConflictParams(msgspec.Struct):
    """Parameters for smp/conflict."""

    entity: str = ""
    proposed_change: str = ""
    context: dict[str, Any] = msgspec.field(default_factory=dict)


class WhyParams(msgspec.Struct):
    """Parameters for smp/why."""

    entity: str = ""
    relationship: str = ""
    depth: int = 3


class TelemetryParams(msgspec.Struct):
    """Parameters for smp/telemetry."""

    action: str = "get_stats"
    node_id: str | None = None
    threshold: int | None = None


class TelemetryHotParams(msgspec.Struct):
    """Parameters for smp/telemetry/hot."""

    node_id: str


class TelemetryNodeParams(msgspec.Struct):
    """Parameters for smp/telemetry/node."""

    node_id: str


# ---------------------------------------------------------------------------
# SMP(3) Handoff Models
# ---------------------------------------------------------------------------


class ReviewCreateParams(msgspec.Struct):
    """Parameters for smp/review/create."""

    session_id: str = ""
    files_changed: list[str] = msgspec.field(default_factory=list)
    diff_summary: str = ""
    reviewers: list[str] = msgspec.field(default_factory=list)


class ReviewApproveParams(msgspec.Struct):
    """Parameters for smp/review/approve."""

    review_id: str = ""
    reviewer: str = ""


class ReviewRejectParams(msgspec.Struct):
    """Parameters for smp/review/reject."""

    review_id: str = ""
    reviewer: str = ""
    reason: str = ""


class ReviewCommentParams(msgspec.Struct):
    """Parameters for smp/review/comment."""

    review_id: str = ""
    author: str = ""
    comment: str = ""
    file_path: str | None = None
    line: int | None = None


class PRCreateParams(msgspec.Struct):
    """Parameters for smp/pr/create."""

    review_id: str = ""
    title: str = ""
    body: str = ""
    branch: str = ""
    base_branch: str = "main"


# ---------------------------------------------------------------------------
# SMP(3) Sandbox Models
# ---------------------------------------------------------------------------


class SandboxSpawnParams(msgspec.Struct):
    """Parameters for smp/sandbox/spawn."""

    name: str | None = None
    template: str | None = None
    files: dict[str, str] = msgspec.field(default_factory=dict)


class SandboxExecuteParams(msgspec.Struct):
    """Parameters for smp/sandbox/execute."""

    sandbox_id: str = ""
    command: list[str] = msgspec.field(default_factory=list)
    stdin: str | None = None
    timeout: int | None = None


class SandboxKillParams(msgspec.Struct):
    """Parameters for smp/sandbox/kill."""

    execution_id: str = ""


# ---------------------------------------------------------------------------
# SMP(3) Integrity Models
# ---------------------------------------------------------------------------


class IntegrityCheckParams(msgspec.Struct):
    """Parameters for smp/integrity/check."""

    node_id: str = ""
    current_state: dict[str, Any] = msgspec.field(default_factory=dict)


class IntegrityBaselineParams(msgspec.Struct):
    """Parameters for smp/integrity/baseline."""

    node_id: str = ""
    state: dict[str, Any] = msgspec.field(default_factory=dict)
