"""msgspec-typed payload structures for the graph journal.

Each :class:`smp.store.graph.journal.RecordType` has a corresponding
``msgspec.Struct`` defined here so we get fast, schema-checked
encode/decode without hand-rolled binary plumbing.

Payloads are msgpack-encoded, which:

* keeps records compact (much smaller than JSON for repeated keys),
* has a deterministic byte layout (good for CRCs),
* round-trips well with the rest of the codebase, which already uses
  msgspec for JSON-RPC.
"""

from __future__ import annotations

from typing import Any

import msgspec

from smp.core.models import GraphEdge, GraphNode


# -- Node / edge -----------------------------------------------------------


class NodeUpsertPayload(msgspec.Struct):
    """Payload for :data:`RecordType.NODE_UPSERT`."""

    node: GraphNode


class NodeDeletePayload(msgspec.Struct):
    """Payload for :data:`RecordType.NODE_DELETE`."""

    node_id: str


class EdgeUpsertPayload(msgspec.Struct):
    """Payload for :data:`RecordType.EDGE_UPSERT`."""

    edge: GraphEdge


class FileDeletePayload(msgspec.Struct):
    """Payload for :data:`RecordType.FILE_DELETE`."""

    file_path: str


# -- Sessions / locks / audit ---------------------------------------------


class SessionUpsertPayload(msgspec.Struct):
    """Payload for :data:`RecordType.SESSION_UPSERT`."""

    session_id: str
    data: dict[str, Any] = msgspec.field(default_factory=dict)


class SessionDeletePayload(msgspec.Struct):
    """Payload for :data:`RecordType.SESSION_DELETE`."""

    session_id: str


class LockUpsertPayload(msgspec.Struct):
    """Payload for :data:`RecordType.LOCK_UPSERT`."""

    file_path: str
    session_id: str
    acquired_at: str = ""
    expires_at: str = ""
    fencing_token: int = 0


class LockReleasePayload(msgspec.Struct):
    """Payload for :data:`RecordType.LOCK_RELEASE`."""

    file_path: str
    session_id: str


class LockReleaseAllPayload(msgspec.Struct):
    """Payload for :data:`RecordType.LOCK_RELEASE_ALL`."""

    session_id: str


class AuditAppendPayload(msgspec.Struct):
    """Payload for :data:`RecordType.AUDIT_APPEND`."""

    event: dict[str, Any] = msgspec.field(default_factory=dict)


class ParseStatusPayload(msgspec.Struct):
    """Payload for :data:`RecordType.PARSE_STATUS`."""

    file_path: str
    parsed: bool = False
    line_count: int = 0
    node_count: int = 0
    stale: bool = False
    parse_time_ms: float | None = None
    content_hash: str = ""


class TransactionPayload(msgspec.Struct):
    """Payload for :data:`RecordType.BEGIN_TX`, ``COMMIT_TX``, ``ABORT_TX``."""

    tx_id: int
    actor: str = ""
    note: str = ""


# -- Codec helpers ---------------------------------------------------------


_msgpack = msgspec.msgpack


def encode(payload: msgspec.Struct) -> bytes:
    """Encode a typed payload to msgpack bytes."""
    return _msgpack.encode(payload)


def decode(data: bytes, struct_type: type[msgspec.Struct]) -> Any:
    """Decode msgpack bytes into the supplied struct type."""
    return _msgpack.decode(data, type=struct_type)


__all__ = [
    "AuditAppendPayload",
    "EdgeUpsertPayload",
    "FileDeletePayload",
    "LockReleaseAllPayload",
    "LockReleasePayload",
    "LockUpsertPayload",
    "NodeDeletePayload",
    "NodeUpsertPayload",
    "ParseStatusPayload",
    "SessionDeletePayload",
    "SessionUpsertPayload",
    "TransactionPayload",
    "decode",
    "encode",
]
