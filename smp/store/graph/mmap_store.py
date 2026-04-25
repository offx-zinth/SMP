from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from smp.store.graph.parser import CodeParser, ParsedFile
    from smp.store.graph.scheduler import BackgroundScheduler

from smp.core.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    SemanticProperties,
    StructuralProperties,
)
from smp.store.graph.edge_store import EdgeStore
from smp.store.graph.index import CritBitIndex, RadixIndex
from smp.store.graph.manifest import FileManifest
from smp.store.graph.mmap_file import OFF_ROOTS, MMapFile
from smp.store.graph.node_store import NodeStore
from smp.store.graph.string_pool import StringPool
from smp.store.interfaces import GraphStore


@dataclass
class ParseStatus:
    """Status of a parsed file."""

    parsed: bool
    line_count: int
    node_count: int
    stale: bool = False
    parse_time_ms: float | None = None


class MMapGraphStore(GraphStore):
    """Memory-mapped graph store implementation."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.file = MMapFile(self.path)

        self._off_index = OFF_ROOTS
        self._off_radix = OFF_ROOTS + 4
        self._off_strings = OFF_ROOTS + 8
        self._off_nodes = OFF_ROOTS + 12
        self._off_manifest = OFF_ROOTS + 16

        self.index: CritBitIndex | None = None
        self.radix: RadixIndex | None = None
        self.strings: StringPool | None = None
        self.nodes_store: NodeStore | None = None
        self.edges_store: EdgeStore | None = None
        self.manifest: FileManifest | None = None

        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, list[GraphEdge]] = {}
        self._edge_index: dict[str, list[GraphEdge]] = {}

        self._parser: CodeParser | None = None
        self._scheduler: BackgroundScheduler | None = None
        self._parse_status: dict[str, ParseStatus] = {}
        self._parsed_files: dict[str, ParsedFile] = {}

    async def connect(self) -> None:
        self.file.open()
        self.index = CritBitIndex(self.file, self._off_index)
        self.radix = RadixIndex(self.file, self._off_radix)
        self.strings = StringPool(self.file, self._off_strings)
        self.nodes_store = NodeStore(self.file, self._off_nodes)
        self.edges_store = EdgeStore(self.file)
        self.manifest = FileManifest(self.file, self._off_manifest)

    async def close(self) -> None:
        if self._scheduler:
            self._scheduler.stop()
        self.file.close()

    async def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
        self._nodes.clear()
        self._edges.clear()
        self._edge_index.clear()
        self._parse_status.clear()
        self._parsed_files.clear()
        await self.connect()

    async def upsert_node(self, node: GraphNode) -> None:
        self._nodes[node.id] = node
        if self.index:
            self.index.insert(node.id, 0)
        if self.radix:
            self.radix.insert(node.file_path, 0)

    async def upsert_nodes(self, nodes: Sequence[GraphNode]) -> None:
        for node in nodes:
            await self.upsert_node(node)

    async def get_node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    async def delete_node(self, node_id: str) -> bool:
        if node_id in self._nodes:
            del self._nodes[node_id]
            if node_id in self._edges:
                del self._edges[node_id]
            for edges in self._edge_index.values():
                edges[:] = [e for e in edges if e.target_id != node_id]
            return True
        return False

    async def delete_nodes_by_file(self, file_path: str) -> int:
        to_delete = [nid for nid, n in self._nodes.items() if n.file_path == file_path]
        for nid in to_delete:
            await self.delete_node(nid)
        return len(to_delete)

    async def upsert_edge(self, edge: GraphEdge) -> None:
        if edge.source_id not in self._edges:
            self._edges[edge.source_id] = []
        self._edges[edge.source_id].append(edge)

        if edge.target_id not in self._edge_index:
            self._edge_index[edge.target_id] = []
        self._edge_index[edge.target_id].append(edge)

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

    def _on_file_parsed(self, file_path: str, parsed: ParsedFile) -> None:
        self._parsed_files[file_path] = parsed
        self._parse_status[file_path] = ParseStatus(
            parsed=True,
            line_count=parsed.line_count,
            node_count=len(parsed.nodes),
        )

    async def parse_file(self, file_path: str) -> list[GraphNode]:
        parsed = self._get_parser().parse_file(file_path)

        self._parsed_files[file_path] = parsed
        self._parse_status[file_path] = ParseStatus(
            parsed=True,
            line_count=parsed.line_count,
            node_count=len(parsed.nodes),
        )

        graph_nodes: list[GraphNode] = []
        for pnode in parsed.nodes:
            graph_nodes.append(
                GraphNode(
                    id=pnode.node_id,
                    type=NodeType(pnode.type.upper()),
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

        await self.upsert_nodes(graph_nodes)

        for ec in parsed.edge_candidates:
            await self.upsert_edge(
                GraphEdge(
                    source_id=ec.source_id,
                    target_id=f"::{ec.target_name}::",
                    type=EdgeType(ec.edge_type.upper()),
                )
            )

        return graph_nodes

    async def ensure_parsed(self, file_path: str) -> list[GraphNode]:
        status = self._parse_status.get(file_path)
        if status and status.parsed and not status.stale:
            return [n for n in self._nodes.values() if n.file_path == file_path]
        return await self.parse_file(file_path)

    async def pre_parse(self, count: int, min_priority: int = 50) -> int:
        scheduler = self._get_scheduler()
        if scheduler.pending_count == 0:
            return 0
        return min(count, scheduler.pending_count)

    async def get_parse_status(self, file_path: str) -> ParseStatus:
        return self._parse_status.get(
            file_path,
            ParseStatus(parsed=False, line_count=0, node_count=0),
        )

    async def wait_for_parse(self, file_path: str, timeout: float) -> bool:
        import asyncio

        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            status = self._parse_status.get(file_path)
            if status and status.parsed:
                return True
            await asyncio.sleep(0.1)
        return False

    async def upsert_session(self, session: Any) -> None:
        pass

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        return None

    async def delete_session(self, session_id: str) -> bool:
        return False

    async def upsert_lock(self, file_path: str, session_id: str) -> None:
        pass

    async def get_lock(self, file_path: str) -> dict[str, Any] | None:
        return None

    async def release_lock(self, file_path: str, session_id: str) -> bool:
        return False

    async def release_all_locks(self, session_id: str) -> int:
        return 0
