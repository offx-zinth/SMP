"""Memory-mapped graph store with durable append-only journal.

Design
------

The store keeps two views of the graph:

* an *in-memory* set of dicts (``_nodes``, ``_edges`` etc.) used for
  fast reads and traversal,
* an *on-disk* append-only journal (managed by
  :class:`smp.store.graph.journal.Journal`) that records every mutation.

On startup the journal is replayed and the in-memory dicts are
reconstructed, which means restarting the server preserves the full
graph state.  This is the foundation for SPEC's "10M+ LOC" persistence
story; later phases add a write-ahead log for transaction grouping
(Phase 2) and enterprise observability around the same primitives.

The store remains async-friendly because all journal writes are
synchronous from Python's point of view (single ``mmap`` slice
assignment) but cheap enough not to block the event loop in practice.
"""

from __future__ import annotations

import asyncio
import enum
import hashlib
import threading
from collections import deque
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from smp.store.graph.parser import CodeParser, ParsedFile
    from smp.store.graph.scheduler import BackgroundScheduler
    from smp.store.graph.watcher import FileWatcher

from smp.core.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    SemanticProperties,
    StructuralProperties,
)
from smp.logging import get_logger
from smp.store.graph.journal import Journal, JournalCorruption, RecordType
from smp.store.graph.mmap_file import MMapFile
from smp.store.graph.query import QueryEngine, QueryResult, parse
from smp.store.graph.records import (
    AuditAppendPayload,
    EdgeUpsertPayload,
    FileDeletePayload,
    LockReleaseAllPayload,
    LockReleasePayload,
    LockUpsertPayload,
    NodeDeletePayload,
    NodeUpsertPayload,
    ParseStatusPayload,
    SessionDeletePayload,
    SessionUpsertPayload,
    TransactionPayload,
    decode,
    encode,
)
from smp.store.interfaces import GraphStore


class DurabilityMode(enum.StrEnum):
    """How aggressively the store flushes records to disk.

    * ``BEST_EFFORT`` — rely on the OS page cache; fastest, weakest
      durability guarantee.  Use for development / tests.
    * ``PERIODIC``    — flush every N writes (and on close); good throughput,
      bounded data loss window on crash.
    * ``SYNC``        — fsync after every commit; strongest guarantee.
    """

    BEST_EFFORT = "best_effort"
    PERIODIC = "periodic"
    SYNC = "sync"

log = get_logger(__name__)

_REPARSE_PRIORITY: float = 85.0
_INVALIDATE_PRIORITY: float = 90.0


@dataclass
class ParseStatus:
    """Status of a parsed file (per-file metadata held in memory)."""

    parsed: bool
    line_count: int
    node_count: int
    stale: bool = False
    parse_time_ms: float | None = None


class MMapGraphStore(GraphStore):
    """Durable memory-mapped graph store.

    The on-disk format is an append-only journal of mutation records;
    the in-memory dicts are reconstructed by replaying that journal at
    startup and kept in sync with new mutations.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        durability: DurabilityMode | str = DurabilityMode.BEST_EFFORT,
        flush_every: int = 64,
    ) -> None:
        self.path = Path(path)
        self.file = MMapFile(self.path)
        self.journal = Journal(self.file)
        self._durability = DurabilityMode(durability)
        self._flush_every = max(1, int(flush_every))
        self._writes_since_flush: int = 0

        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, list[GraphEdge]] = {}
        self._edge_index: dict[str, list[GraphEdge]] = {}

        self._sessions: dict[str, dict[str, Any]] = {}
        self._locks: dict[str, dict[str, Any]] = {}
        self._audit: list[dict[str, Any]] = []
        self._fencing_counter: int = 0

        # Transactions.
        self._tx_counter: int = 0
        self._active_tx_id: int | None = None
        self._tx_lock = asyncio.Lock()
        self._write_lock = threading.Lock()

        self._parser: CodeParser | None = None
        self._scheduler: BackgroundScheduler | None = None
        self._watcher: FileWatcher | None = None
        self._parse_status: dict[str, ParseStatus] = {}
        self._parsed_files: dict[str, ParsedFile] = {}
        self._file_hashes: dict[str, str] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open the underlying file and replay the journal."""
        self.file.open()
        self._loop = asyncio.get_running_loop()
        self._replay_journal()

    async def close(self) -> None:
        """Stop background workers and flush + close the file."""
        if self._watcher:
            self._watcher.stop()
            self._watcher = None
        if self._scheduler:
            self._scheduler.stop()
            self._scheduler = None
        self.file.flush()
        self.file.fsync()
        self.file.close()
        self._loop = None

    async def clear(self) -> None:
        """Drop all data on disk and in memory."""
        if self.path.exists():
            self.file.close()
            self.path.unlink()
        self._nodes.clear()
        self._edges.clear()
        self._edge_index.clear()
        self._sessions.clear()
        self._locks.clear()
        self._audit.clear()
        self._parse_status.clear()
        self._parsed_files.clear()
        self._file_hashes.clear()
        self._fencing_counter = 0
        await self.connect()

    # ------------------------------------------------------------------
    # Journal helpers
    # ------------------------------------------------------------------

    def _append(self, rtype: RecordType, payload: bytes) -> None:
        """Append a record to the journal, honoring the durability mode.

        Writes serialise on a thread lock so concurrent ``asyncio`` tasks
        cooperating on the same store never interleave bytes inside the
        mmap region.
        """
        with self._write_lock:
            self.journal.append(rtype, payload, fsync=False)
            self._writes_since_flush += 1
            if self._durability is DurabilityMode.SYNC:
                self.file.fsync()
                self._writes_since_flush = 0
            elif (
                self._durability is DurabilityMode.PERIODIC
                and self._writes_since_flush >= self._flush_every
            ):
                self.file.flush()
                self._writes_since_flush = 0

    def _replay_journal(self) -> None:
        """Walk the on-disk journal and rebuild in-memory state.

        Records inside an open (uncommitted) transaction are buffered and
        applied only when a matching ``COMMIT_TX`` is observed; any
        outstanding buffer at the end of the log is silently discarded
        (these are the records of a transaction that crashed before it
        could commit).
        """
        committed = 0
        aborted = 0
        dropped = 0
        buffer: list[tuple[RecordType, bytes]] = []
        in_tx = False
        try:
            for rtype, payload, _ in self.journal.replay():
                if rtype is RecordType.BEGIN_TX:
                    if in_tx:
                        dropped += len(buffer)
                        buffer = []
                    in_tx = True
                    tx = decode(payload, TransactionPayload)
                    self._tx_counter = max(self._tx_counter, tx.tx_id)
                elif rtype is RecordType.COMMIT_TX:
                    if in_tx:
                        for r_type, r_payload in buffer:
                            self._apply_record(r_type, r_payload)
                        committed += 1
                    buffer = []
                    in_tx = False
                elif rtype is RecordType.ABORT_TX:
                    aborted += 1
                    dropped += len(buffer)
                    buffer = []
                    in_tx = False
                else:
                    if in_tx:
                        buffer.append((rtype, payload))
                    else:
                        self._apply_record(rtype, payload)
            if buffer:
                dropped += len(buffer)
        except JournalCorruption:
            log.exception("journal_replay_failed", path=str(self.path))
            raise
        log.info(
            "journal_replayed",
            path=str(self.path),
            nodes=len(self._nodes),
            edges=sum(len(v) for v in self._edges.values()),
            sessions=len(self._sessions),
            locks=len(self._locks),
            tx_committed=committed,
            tx_aborted=aborted,
            tx_records_dropped=dropped,
        )

    def _apply_record(self, rtype: RecordType, payload: bytes) -> None:  # noqa: C901, PLR0912
        if rtype is RecordType.NODE_UPSERT:
            data = decode(payload, NodeUpsertPayload)
            self._apply_node_upsert(data.node)
        elif rtype is RecordType.NODE_DELETE:
            data = decode(payload, NodeDeletePayload)
            self._apply_node_delete(data.node_id)
        elif rtype is RecordType.EDGE_UPSERT:
            data = decode(payload, EdgeUpsertPayload)
            self._apply_edge_upsert(data.edge)
        elif rtype is RecordType.FILE_DELETE:
            data = decode(payload, FileDeletePayload)
            self._apply_file_delete(data.file_path)
        elif rtype is RecordType.SESSION_UPSERT:
            data = decode(payload, SessionUpsertPayload)
            self._sessions[data.session_id] = dict(data.data)
        elif rtype is RecordType.SESSION_DELETE:
            data = decode(payload, SessionDeletePayload)
            self._sessions.pop(data.session_id, None)
        elif rtype is RecordType.LOCK_UPSERT:
            data = decode(payload, LockUpsertPayload)
            self._locks[data.file_path] = {
                "session_id": data.session_id,
                "acquired_at": data.acquired_at,
                "expires_at": data.expires_at,
                "fencing_token": data.fencing_token,
            }
            self._fencing_counter = max(self._fencing_counter, data.fencing_token)
        elif rtype is RecordType.LOCK_RELEASE:
            data = decode(payload, LockReleasePayload)
            existing = self._locks.get(data.file_path)
            if existing and existing.get("session_id") == data.session_id:
                self._locks.pop(data.file_path, None)
        elif rtype is RecordType.LOCK_RELEASE_ALL:
            data = decode(payload, LockReleaseAllPayload)
            for fp, info in list(self._locks.items()):
                if info.get("session_id") == data.session_id:
                    self._locks.pop(fp, None)
        elif rtype is RecordType.AUDIT_APPEND:
            data = decode(payload, AuditAppendPayload)
            self._audit.append(dict(data.event))
        elif rtype is RecordType.PARSE_STATUS:
            data = decode(payload, ParseStatusPayload)
            self._parse_status[data.file_path] = ParseStatus(
                parsed=data.parsed,
                line_count=data.line_count,
                node_count=data.node_count,
                stale=data.stale,
                parse_time_ms=data.parse_time_ms,
            )
            if data.content_hash:
                self._file_hashes[data.file_path] = data.content_hash

    # ------------------------------------------------------------------
    # In-memory mutators (used by both live writes and replay)
    # ------------------------------------------------------------------

    def _apply_node_upsert(self, node: GraphNode) -> None:
        self._nodes[node.id] = node

    def _apply_node_delete(self, node_id: str) -> bool:
        if node_id not in self._nodes:
            return False
        del self._nodes[node_id]
        if node_id in self._edges:
            del self._edges[node_id]
        for src, edges in list(self._edges.items()):
            self._edges[src] = [e for e in edges if e.target_id != node_id]
        for tgt, edges in list(self._edge_index.items()):
            self._edge_index[tgt] = [e for e in edges if e.source_id != node_id]
        self._edge_index.pop(node_id, None)
        return True

    def _apply_edge_upsert(self, edge: GraphEdge) -> None:
        self._edges.setdefault(edge.source_id, []).append(edge)
        self._edge_index.setdefault(edge.target_id, []).append(edge)

    def _apply_file_delete(self, file_path: str) -> int:
        to_delete = [nid for nid, n in self._nodes.items() if n.file_path == file_path]
        for nid in to_delete:
            self._apply_node_delete(nid)
        return len(to_delete)

    # ------------------------------------------------------------------
    # Node CRUD (durable)
    # ------------------------------------------------------------------

    async def upsert_node(self, node: GraphNode) -> None:
        self._apply_node_upsert(node)
        self._append(RecordType.NODE_UPSERT, encode(NodeUpsertPayload(node=node)))

    async def upsert_nodes(self, nodes: Sequence[GraphNode]) -> None:
        for node in nodes:
            await self.upsert_node(node)

    async def get_node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    async def delete_node(self, node_id: str) -> bool:
        if node_id not in self._nodes:
            return False
        self._apply_node_delete(node_id)
        self._append(RecordType.NODE_DELETE, encode(NodeDeletePayload(node_id=node_id)))
        return True

    async def delete_nodes_by_file(self, file_path: str) -> int:
        count = sum(1 for n in self._nodes.values() if n.file_path == file_path)
        if count == 0:
            return 0
        self._apply_file_delete(file_path)
        self._append(RecordType.FILE_DELETE, encode(FileDeletePayload(file_path=file_path)))
        return count

    # ------------------------------------------------------------------
    # Edge CRUD (durable)
    # ------------------------------------------------------------------

    async def upsert_edge(self, edge: GraphEdge) -> None:
        self._apply_edge_upsert(edge)
        self._append(RecordType.EDGE_UPSERT, encode(EdgeUpsertPayload(edge=edge)))

    async def upsert_edges(self, edges: Sequence[GraphEdge]) -> None:
        for edge in edges:
            await self.upsert_edge(edge)

    async def get_edges(
        self,
        node_id: str,
        edge_type: EdgeType | None = None,
        direction: str = "both",
    ) -> list[GraphEdge]:
        results: list[GraphEdge] = []
        if direction in ("outgoing", "both"):
            results.extend(self._edges.get(node_id, []))
        if direction in ("incoming", "both"):
            results.extend(self._edge_index.get(node_id, []))
        if edge_type:
            results = [e for e in results if e.type == edge_type]
        return results

    async def get_neighbors(
        self,
        node_id: str,
        edge_type: EdgeType | None = None,
        depth: int = 1,
    ) -> list[GraphNode]:
        edge_types: EdgeType | list[EdgeType] = edge_type if edge_type else []
        return await self.traverse(node_id, edge_types, depth, max_nodes=1000, direction="outgoing")

    async def traverse(
        self,
        start_id: str,
        edge_type: EdgeType | list[EdgeType],
        depth: int,
        max_nodes: int = 100,
        direction: str = "outgoing",
    ) -> list[GraphNode]:
        if start_id not in self._nodes:
            return []

        visited: set[str] = {start_id}
        queue: deque[tuple[str, int]] = deque([(start_id, 0)])
        results: list[GraphNode] = [self._nodes[start_id]]

        edge_types: set[EdgeType] = set()
        if edge_type:
            if isinstance(edge_type, list):
                edge_types.update(edge_type)
            else:
                edge_types.add(edge_type)

        while queue and len(results) < max_nodes:
            current_id, current_depth = queue.popleft()
            if current_depth >= depth:
                continue

            edges = await self.get_edges(current_id, None, direction)
            for edge in edges:
                if edge_types and edge.type not in edge_types:
                    continue

                target_id = edge.target_id if direction != "incoming" else edge.source_id
                if target_id in visited:
                    continue
                if target_id in self._nodes:
                    visited.add(target_id)
                    results.append(self._nodes[target_id])
                    queue.append((target_id, current_depth + 1))

        return results

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def find_nodes(
        self,
        *,
        type: NodeType | None = None,
        file_path: str | None = None,
        name: str | None = None,
    ) -> list[GraphNode]:
        results = list(self._nodes.values())
        if type:
            results = [n for n in results if n.type == type]
        if file_path:
            results = [n for n in results if n.file_path == file_path]
        if name:
            results = [n for n in results if n.structural.name == name]
        return results

    async def search_nodes(
        self,
        query_terms: list[str],
        match: str = "any",
        node_types: list[str] | None = None,
        tags: list[str] | None = None,
        scope: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        results: list[tuple[int, GraphNode]] = []
        for node in self._nodes.values():
            if node_types and node.type.value not in node_types:
                continue
            score = 0
            for term in query_terms:
                term_lower = term.lower()
                if term_lower in node.structural.name.lower():
                    score += 3
                if node.semantic.docstring and term_lower in node.semantic.docstring.lower():
                    score += 2
                if node.semantic.description and term_lower in node.semantic.description.lower():
                    score += 1
            if score > 0:
                results.append((score, node))
        results.sort(key=lambda x: x[0], reverse=True)
        return [
            {
                "id": node.id,
                "type": node.type.value,
                "name": node.structural.name,
                "file_path": node.file_path,
                "score": score,
            }
            for score, node in results[:top_k]
        ]

    async def count_nodes(self) -> int:
        return len(self._nodes)

    async def count_edges(self) -> int:
        return sum(len(e) for e in self._edges.values())

    # ------------------------------------------------------------------
    # Parser / scheduler / watcher
    # ------------------------------------------------------------------

    def _get_parser(self) -> CodeParser:
        if self._parser is None:
            from smp.store.graph.parser import CodeParser

            self._parser = CodeParser()
        return self._parser

    def _get_scheduler(self) -> BackgroundScheduler:
        if self._scheduler is None:
            from smp.store.graph.scheduler import BackgroundScheduler

            self._scheduler = BackgroundScheduler(self._get_parser())
            self._scheduler.callback = self._on_file_parsed
            self._scheduler.start()
        return self._scheduler

    def _get_watcher(self) -> FileWatcher:
        if self._watcher is None:
            from smp.store.graph.watcher import FileWatcher

            self._watcher = FileWatcher(self._on_file_changed)
        return self._watcher

    @staticmethod
    def _normalise_path(file_path: str | Path) -> str:
        try:
            return str(Path(file_path).resolve())
        except OSError:
            return str(Path(file_path).absolute())

    @staticmethod
    def _compute_file_hash(file_path: str) -> str:
        with open(file_path, "rb") as fh:
            content = fh.read()
        return hashlib.blake2b(content, digest_size=8).hexdigest()

    def _parsed_to_graph_nodes(self, file_path: str, parsed: ParsedFile) -> list[GraphNode]:
        graph_nodes: list[GraphNode] = []
        for pnode in parsed.nodes:
            try:
                node_type = NodeType(pnode.type)
            except ValueError:
                node_type = NodeType.FUNCTION
            graph_nodes.append(
                GraphNode(
                    id=pnode.node_id,
                    type=node_type,
                    file_path=file_path,
                    structural=StructuralProperties(
                        name=pnode.name,
                        file=file_path,
                        signature=pnode.signature,
                        start_line=pnode.start_line,
                        end_line=pnode.end_line,
                    ),
                    semantic=SemanticProperties(
                        docstring=pnode.docstring,
                    ),
                )
            )
        return graph_nodes

    async def _apply_parsed_file(self, file_path: str, parsed: ParsedFile) -> list[GraphNode]:
        await self.delete_nodes_by_file(file_path)

        graph_nodes = self._parsed_to_graph_nodes(file_path, parsed)
        await self.upsert_nodes(graph_nodes)

        for ec in parsed.edge_candidates:
            await self.upsert_edge(
                GraphEdge(
                    source_id=ec.source_id,
                    target_id=f"::{ec.target_name}::",
                    type=EdgeType(ec.edge_type),
                )
            )

        if parsed.resolved_edges:
            await self.upsert_edges(parsed.resolved_edges)

        self._parsed_files[file_path] = parsed
        self._file_hashes[file_path] = parsed.content_hash
        status = ParseStatus(
            parsed=True,
            line_count=parsed.line_count,
            node_count=len(parsed.nodes),
            stale=False,
        )
        self._parse_status[file_path] = status
        self._append(
            RecordType.PARSE_STATUS,
            encode(
                ParseStatusPayload(
                    file_path=file_path,
                    parsed=True,
                    line_count=parsed.line_count,
                    node_count=len(parsed.nodes),
                    stale=False,
                    content_hash=parsed.content_hash,
                )
            ),
        )
        return graph_nodes

    def _on_file_parsed(self, file_path: str, parsed: ParsedFile) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            future = asyncio.run_coroutine_threadsafe(self._apply_parsed_file(file_path, parsed), loop)
            future.result(timeout=30.0)
        except Exception:
            log.exception("apply_parsed_file_failed", file_path=file_path)

    def _on_file_changed(self, file_path: str, event_type: str) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        if event_type == "deleted":
            asyncio.run_coroutine_threadsafe(self._handle_file_deleted(file_path), loop)
            return

        try:
            new_hash = self._compute_file_hash(file_path)
        except OSError:
            return

        old_hash = self._file_hashes.get(file_path)
        if old_hash == new_hash:
            return

        status = self._parse_status.get(file_path)
        if status is not None:
            status.stale = True

        scheduler = self._get_scheduler()
        scheduler.enqueue(file_path, priority=_REPARSE_PRIORITY)
        log.info("file_changed", path=file_path, event_type=event_type)

    async def _handle_file_deleted(self, file_path: str) -> None:
        await self.delete_nodes_by_file(file_path)
        self._parse_status.pop(file_path, None)
        self._parsed_files.pop(file_path, None)
        self._file_hashes.pop(file_path, None)
        log.info("file_deleted", path=file_path)

    async def parse_file(self, file_path: str) -> list[GraphNode]:
        resolved = self._normalise_path(file_path)
        parsed = self._get_parser().parse_file(resolved)
        return await self._apply_parsed_file(resolved, parsed)

    async def ensure_parsed(self, file_path: str) -> list[GraphNode]:
        resolved = self._normalise_path(file_path)
        status = self._parse_status.get(resolved)
        if status and status.parsed and not status.stale:
            return [n for n in self._nodes.values() if n.file_path == resolved]
        return await self.parse_file(resolved)

    async def pre_parse(self, count: int, min_priority: int = 50) -> int:
        scheduler = self._get_scheduler()
        if scheduler.pending_count == 0:
            return 0
        return min(count, scheduler.pending_count)

    def watch_directories(self, paths: Iterable[str | Path]) -> None:
        watcher = self._get_watcher()
        for path in paths:
            watcher.watch_directory(path)
        if not watcher.is_running:
            self._get_scheduler()
            watcher.start()

    def unwatch_directory(self, path: str | Path) -> None:
        if self._watcher is None:
            return
        self._watcher.unwatch_directory(path)

    async def invalidate_file(self, file_path: str) -> None:
        resolved = self._normalise_path(file_path)
        if not Path(resolved).exists():
            await self._handle_file_deleted(resolved)
            return

        status = self._parse_status.get(resolved)
        if status is not None:
            status.stale = True

        scheduler = self._get_scheduler()
        scheduler.enqueue(resolved, priority=_INVALIDATE_PRIORITY)
        log.info("file_invalidated", path=resolved)

    async def get_parse_status(self, file_path: str) -> ParseStatus:
        resolved = self._normalise_path(file_path)
        return self._parse_status.get(
            resolved,
            ParseStatus(parsed=False, line_count=0, node_count=0),
        )

    async def wait_for_parse(self, file_path: str, timeout: float) -> bool:
        resolved = self._normalise_path(file_path)
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            status = self._parse_status.get(resolved)
            if status and status.parsed and not status.stale:
                return True
            await asyncio.sleep(0.1)
        return False

    async def query(
        self,
        expression: str,
        params: dict[str, Any] | None = None,
        *,
        max_results: int = 10_000,
    ) -> QueryResult:
        del params
        query = parse(expression)
        engine = QueryEngine(self)
        return await engine.execute(query, max_results=max_results)

    # ------------------------------------------------------------------
    # Sessions / locks / audit (durable)
    # ------------------------------------------------------------------

    async def upsert_session(self, session: Any) -> None:
        if isinstance(session, dict):
            session_id = str(session.get("session_id") or session.get("id") or "")
            data = dict(session)
        else:
            session_id = str(getattr(session, "session_id", ""))
            data = dict(getattr(session, "__dict__", {}))
        if not session_id:
            raise ValueError("session must include a session_id")
        self._sessions[session_id] = data
        self._append(
            RecordType.SESSION_UPSERT,
            encode(SessionUpsertPayload(session_id=session_id, data=data)),
        )

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        record = self._sessions.get(session_id)
        return dict(record) if record is not None else None

    async def delete_session(self, session_id: str) -> bool:
        if session_id not in self._sessions:
            return False
        self._sessions.pop(session_id, None)
        self._append(
            RecordType.SESSION_DELETE,
            encode(SessionDeletePayload(session_id=session_id)),
        )
        return True

    async def upsert_lock(
        self,
        file_path: str,
        session_id: str,
        *,
        acquired_at: str = "",
        expires_at: str = "",
    ) -> None:
        self._fencing_counter += 1
        token = self._fencing_counter
        self._locks[file_path] = {
            "session_id": session_id,
            "acquired_at": acquired_at,
            "expires_at": expires_at,
            "fencing_token": token,
        }
        self._append(
            RecordType.LOCK_UPSERT,
            encode(
                LockUpsertPayload(
                    file_path=file_path,
                    session_id=session_id,
                    acquired_at=acquired_at,
                    expires_at=expires_at,
                    fencing_token=token,
                )
            ),
        )

    async def get_lock(self, file_path: str) -> dict[str, Any] | None:
        record = self._locks.get(file_path)
        return dict(record) if record is not None else None

    async def release_lock(self, file_path: str, session_id: str) -> bool:
        existing = self._locks.get(file_path)
        if not existing or existing.get("session_id") != session_id:
            return False
        self._locks.pop(file_path, None)
        self._append(
            RecordType.LOCK_RELEASE,
            encode(LockReleasePayload(file_path=file_path, session_id=session_id)),
        )
        return True

    async def release_all_locks(self, session_id: str) -> int:
        held = [fp for fp, info in self._locks.items() if info.get("session_id") == session_id]
        if not held:
            return 0
        for fp in held:
            self._locks.pop(fp, None)
        self._append(
            RecordType.LOCK_RELEASE_ALL,
            encode(LockReleaseAllPayload(session_id=session_id)),
        )
        return len(held)

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    async def append_audit(self, event: dict[str, Any]) -> None:
        """Append an audit event durably."""
        record = dict(event)
        self._audit.append(record)
        self._append(RecordType.AUDIT_APPEND, encode(AuditAppendPayload(event=record)))

    async def list_audit(self) -> list[dict[str, Any]]:
        """Return a copy of the audit log."""
        return [dict(e) for e in self._audit]

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def transaction(self, *, actor: str = "", note: str = "") -> AsyncIterator[int]:
        """Group a set of mutations into one atomic on-disk transaction.

        Records written inside the ``async with`` block are durable as a
        unit: if the process crashes before the block exits, a fresh
        :class:`MMapGraphStore` will replay everything *outside* the
        transaction but drop the partial work inside it.

        Yields the assigned ``tx_id`` so callers can correlate audit
        events with transaction boundaries.
        """
        async with self._tx_lock:
            self._tx_counter += 1
            tx_id = self._tx_counter
            self._active_tx_id = tx_id
            self._append(
                RecordType.BEGIN_TX,
                encode(TransactionPayload(tx_id=tx_id, actor=actor, note=note)),
            )
            try:
                yield tx_id
            except BaseException:
                self._append(
                    RecordType.ABORT_TX,
                    encode(TransactionPayload(tx_id=tx_id)),
                )
                self._active_tx_id = None
                self.file.flush()
                raise
            self._append(
                RecordType.COMMIT_TX,
                encode(TransactionPayload(tx_id=tx_id)),
            )
            self._active_tx_id = None
            if self._durability is DurabilityMode.SYNC:
                self.file.fsync()
            elif self._durability is DurabilityMode.PERIODIC:
                self.file.flush()

    @property
    def active_transaction(self) -> int | None:
        """Return the active transaction id, or ``None`` outside any transaction."""
        return self._active_tx_id

    async def flush(self) -> None:
        """Flush all pending writes to the OS page cache."""
        self.file.flush()
        self._writes_since_flush = 0

    async def fsync(self) -> None:
        """Force fsync of the underlying file descriptor."""
        self.file.fsync()
        self._writes_since_flush = 0

    # ------------------------------------------------------------------
    # Integrity
    # ------------------------------------------------------------------

    async def integrity_report(self) -> dict[str, Any]:
        """Walk on-disk invariants and return a structured report.

        The report covers:

        * journal record-count and CRC validity (via re-replay),
        * orphaned outgoing edges (source node missing),
        * dangling incoming edges (target node missing),
        * lock entries pointing at unknown sessions,
        * file-size vs. ``data_end`` consistency.

        It is read-only — nothing on disk is modified.
        """
        report: dict[str, Any] = {
            "ok": True,
            "errors": [],
            "warnings": [],
            "stats": {},
        }

        record_count = 0
        type_counts: dict[str, int] = {}
        try:
            for rtype, _payload, _offset in self.journal.replay():
                record_count += 1
                type_counts[rtype.name] = type_counts.get(rtype.name, 0) + 1
        except JournalCorruption as exc:
            report["ok"] = False
            report["errors"].append({"kind": "journal_corruption", "detail": str(exc)})

        report["stats"]["records"] = record_count
        report["stats"]["records_by_type"] = type_counts
        report["stats"]["nodes"] = len(self._nodes)
        report["stats"]["edges"] = sum(len(v) for v in self._edges.values())
        report["stats"]["sessions"] = len(self._sessions)
        report["stats"]["locks"] = len(self._locks)
        report["stats"]["audit_events"] = len(self._audit)
        report["stats"]["file_size"] = self.file.size
        report["stats"]["data_end"] = self.file.data_region_end

        orphan_outgoing: list[dict[str, str]] = []
        dangling_incoming: list[dict[str, str]] = []
        for src, edges in self._edges.items():
            if src not in self._nodes:
                orphan_outgoing.append({"source_id": src, "edge_count": str(len(edges))})
            for edge in edges:
                if edge.target_id not in self._nodes and not edge.target_id.startswith("::"):
                    dangling_incoming.append({"source_id": src, "target_id": edge.target_id})
        if orphan_outgoing:
            report["warnings"].append(
                {"kind": "orphan_outgoing_edges", "count": len(orphan_outgoing), "samples": orphan_outgoing[:5]}
            )
        if dangling_incoming:
            report["warnings"].append(
                {"kind": "dangling_incoming_edges", "count": len(dangling_incoming), "samples": dangling_incoming[:5]}
            )

        unknown_session_locks = [
            {"file_path": fp, "session_id": info.get("session_id", "")}
            for fp, info in self._locks.items()
            if info.get("session_id") and info["session_id"] not in self._sessions
        ]
        if unknown_session_locks:
            report["warnings"].append(
                {"kind": "lock_unknown_session", "count": len(unknown_session_locks), "samples": unknown_session_locks[:5]}
            )

        if self.file.data_region_end > self.file.size:
            report["ok"] = False
            report["errors"].append(
                {"kind": "data_end_overflow", "data_end": self.file.data_region_end, "file_size": self.file.size}
            )

        return report
