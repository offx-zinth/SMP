"""Core data models for SMP.

All models use msgspec.Struct for zero-cost serialization and validation.
"""

from __future__ import annotations

import enum
from typing import Any

import msgspec


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class NodeType(str, enum.Enum):
    """Semantic node types extracted from source code."""

    FILE = "FILE"
    MODULE = "MODULE"
    CLASS = "CLASS"
    FUNCTION = "FUNCTION"
    METHOD = "METHOD"
    IMPORT = "IMPORT"
    VARIABLE = "VARIABLE"


class EdgeType(str, enum.Enum):
    """Relationship types between graph nodes."""

    DEFINES = "DEFINES"
    CALLS = "CALLS"
    IMPORTS = "IMPORTS"
    IMPLEMENTS = "IMPLEMENTS"
    CONTAINS = "CONTAINS"
    REFERENCES = "REFERENCES"
    INHERITS = "INHERITS"
    DECORATES = "DECORATES"


class Language(str, enum.Enum):
    """Supported source languages."""

    PYTHON = "python"
    TYPESCRIPT = "typescript"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Semantic enrichment
# ---------------------------------------------------------------------------

class SemanticInfo(msgspec.Struct, frozen=True):
    """LLM-generated semantic metadata for a node."""

    purpose: str = ""
    embedding: list[float] | None = None
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# Graph primitives
# ---------------------------------------------------------------------------

class GraphNode(msgspec.Struct):
    """A single node in the structural graph."""

    id: str
    type: NodeType
    name: str
    file_path: str
    start_line: int = 0
    end_line: int = 0
    signature: str = ""
    docstring: str = ""
    semantic: SemanticInfo | None = None
    metadata: dict[str, str] = msgspec.field(default_factory=dict)

    def fingerprint(self) -> str:
        """Deterministic identity key for deduplication."""
        return f"{self.file_path}::{self.type.value}::{self.name}::{self.start_line}"


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
# Query models
# ---------------------------------------------------------------------------

class NavigateParams(msgspec.Struct):
    """Parameters for smp/navigate."""

    entity_id: str
    depth: int = 1


class TraceParams(msgspec.Struct):
    """Parameters for smp/trace."""

    start_id: str
    edge_type: EdgeType = EdgeType.CALLS
    depth: int = 5
    max_nodes: int = 100


class ContextParams(msgspec.Struct):
    """Parameters for smp/context."""

    file_path: str
    scope: str = "edit"
    include_semantic: bool = True


class ImpactParams(msgspec.Struct):
    """Parameters for smp/impact."""

    entity_id: str
    depth: int = 10


class LocateParams(msgspec.Struct):
    """Parameters for smp/locate."""

    description: str
    top_k: int = 5


class FlowParams(msgspec.Struct):
    """Parameters for smp/flow."""

    start_id: str
    end_id: str
    max_depth: int = 20


class UpdateParams(msgspec.Struct):
    """Parameters for smp/update."""

    file_path: str
    content: str = ""
    language: Language = Language.PYTHON
