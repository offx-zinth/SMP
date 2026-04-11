"""Graph linker module for resolving cross-file references.

Implements the SMP(3) linker spec:
- Resolves namespaced CALLS edges (file::function)
- Supports global linking across the graph
- Handles pending edges for forward references
"""

from __future__ import annotations

from typing import Any

from smp.core.models import Document, EdgeType, GraphEdge, GraphNode, NodeType
from smp.logging import get_logger

log = get_logger(__name__)


class Linker:
    """Resolves cross-file references and creates CALLS edges."""

    def __init__(self) -> None:
        self._pending_edges: list[tuple[GraphEdge, str, str]] = []
        self._import_maps: dict[str, dict[str, tuple[str, str]]] = {}

    def build_import_map(
        self,
        document: Document,
        nodes: list[GraphNode],
    ) -> dict[str, tuple[str, str]]:
        """Build import map from document nodes.

        Returns dict mapping imported names to (module_path, original_name).
        """
        import_map: dict[str, tuple[str, str]] = {}

        for node in nodes:
            if node.type != NodeType.FILE:
                continue

            sig = node.structural.signature
            if "import" not in sig:
                continue

            module_path = node.structural.name.replace(".", "/") + ".py"

            if sig.strip().startswith("from"):
                after_import = sig.split("import", 1)[1]
                for raw_name in after_import.split(","):
                    stripped = raw_name.strip()
                    if not stripped:
                        continue
                    if " as " in stripped:
                        original, alias = stripped.split(" as ", 1)
                        import_map[alias.strip()] = (module_path, original.strip())
                    else:
                        name = stripped.split()[0]
                        import_map[name] = (module_path, name)
            else:
                parts = sig.replace("import", "").strip().split(",")
                for p in parts:
                    stripped = p.strip()
                    if " as " in stripped:
                        original, alias = stripped.split(" as ", 1)
                        import_map[alias.strip()] = (module_path, original.strip())
                    else:
                        name = stripped.split()[0]
                        import_map[name] = (module_path, name)

        self._import_maps[document.file_path] = import_map
        return import_map

    async def resolve_calls(
        self,
        edges: list[GraphEdge],
        nodes: list[GraphNode],
        graph_store: Any,
    ) -> tuple[list[GraphEdge], list[tuple[GraphEdge, str, str]]]:
        """Resolve CALLS edges to target node IDs.

        Returns (resolved_edges, pending_edges).
        """
        name_to_id = {n.structural.name: n.id for n in nodes}
        file_path = nodes[0].file_path if nodes else ""
        import_map = self._import_maps.get(file_path, {})

        resolved: list[GraphEdge] = []
        pending: list[tuple[GraphEdge, str, str]] = []

        for edge in edges:
            if edge.type != EdgeType.CALLS:
                resolved.append(edge)
                continue

            target_id = edge.target_id
            parts = target_id.split("::")

            if len(parts) >= 4 and parts[-1] == "0":
                entity_name = parts[2]

                if entity_name in name_to_id:
                    edge.target_id = name_to_id[entity_name]
                    resolved.append(edge)
                    log.debug("linker_resolved_local", name=entity_name, target=edge.target_id)
                    continue

            if entity_name in import_map:
                module_path, original_name = import_map[entity_name]
                resolved_target = await self._resolve_cross_file(
                    original_name,
                    module_path,
                    graph_store,
                )

                if resolved_target:
                    edge.target_id = resolved_target
                    resolved.append(edge)
                    log.info(
                        "linker_resolved_cross_file",
                        name=entity_name,
                        original=original_name,
                        target=resolved_target,
                    )
                else:
                    fallback = f"{module_path}::Function::{original_name}::1"
                    edge.target_id = fallback
                    pending.append((edge, original_name, module_path))
                    log.info(
                        "linker_cross_file_pending",
                        name=entity_name,
                        original=original_name,
                        target=fallback,
                    )
                resolved.append(edge)
            else:
                resolved.append(edge)

        return resolved, pending

    async def _resolve_cross_file(
        self,
        entity_name: str,
        module_path: str,
        graph_store: Any,
    ) -> str | None:
        """Look up the actual node ID for a cross-file reference."""
        candidates = await graph_store.find_nodes(name=entity_name)
        if not candidates:
            return None

        if not module_path:
            return candidates[0].id

        stem = module_path.rsplit("/", 1)[-1]

        for n in candidates:
            if n.file_path == module_path:
                return n.id

        for n in candidates:
            if n.file_path.endswith(stem):
                return n.id

        return candidates[0].id

    async def resolve_pending(self, graph_store: Any) -> int:
        """Re-attempt pending edge resolutions."""
        if not self._pending_edges:
            return 0

        fixed = 0
        still_pending: list[tuple[GraphEdge, str, str]] = []
        resolved: list[GraphEdge] = []

        for edge, original_name, module_path in self._pending_edges:
            real_id = await self._resolve_cross_file(original_name, module_path, graph_store)
            if real_id:
                edge.target_id = real_id
                log.info(
                    "linker_pending_resolved",
                    original=original_name,
                    target=real_id,
                )
                resolved.append(edge)
                fixed += 1
            else:
                still_pending.append((edge, original_name, module_path))

        if resolved:
            await graph_store.upsert_edges(resolved)

        self._pending_edges = still_pending
        if fixed:
            log.info("resolve_pending_complete", fixed=fixed, remaining=len(still_pending))

        return fixed

    def get_pending_count(self) -> int:
        """Return count of pending edges."""
        return len(self._pending_edges)

    def clear_pending(self) -> None:
        """Clear all pending edges."""
        self._pending_edges.clear()
        log.info("linker_pending_cleared")
