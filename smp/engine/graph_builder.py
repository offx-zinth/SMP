"""Graph builder — maps parsed Documents into the graph store with Global Linking.

Updated for SMP(3) partitioned data model.
"""

from __future__ import annotations

from smp.core.models import Document, GraphEdge, NodeType
from smp.engine.interfaces import GraphBuilder as GraphBuilderInterface
from smp.logging import get_logger
from smp.store.interfaces import GraphStore

log = get_logger(__name__)


class DefaultGraphBuilder(GraphBuilderInterface):
    def __init__(self, graph_store: GraphStore) -> None:
        self._store = graph_store
        self._pending_edges: list[tuple[GraphEdge, str, str]] = []

    async def ingest_document(self, document: Document) -> None:
        name_to_id = {n.structural.name: n.id for n in document.nodes}

        import_map: dict[str, tuple[str, str]] = {}
        for node in document.nodes:
            if node.type != NodeType.FILE:
                continue
            sig = node.structural.signature
            if "import" not in sig:
                continue
            module_name = node.structural.name
            module_path = module_name.replace(".", "/")
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

        if document.nodes:
            await self._store.upsert_nodes(document.nodes)

        resolved_edges: list[GraphEdge] = []
        for edge in document.edges:
            parts = edge.target_id.split("::")
            if len(parts) >= 4 and parts[-1] == "0":
                entity_name = parts[2]

                if entity_name in name_to_id:
                    edge.target_id = name_to_id[entity_name]
                    resolved_edges.append(edge)
                    continue

                # Check if entity_name is a qualified name (e.g., module.function)
                # and if the module prefix is in our import map
                matched_module = None
                original_name = entity_name
                for module_alias, (module_path, module_orig) in import_map.items():
                    if entity_name.startswith(f"{module_alias}."):
                        matched_module = module_alias
                        original_name = entity_name[len(module_alias) + 1 :]
                        break

                if matched_module:
                    module_path, module_orig = import_map[matched_module]
                    target_id = await self._resolve_cross_file(
                        original_name,
                        module_path,
                    )
                    if target_id:
                        edge.target_id = target_id
                        log.info(
                            "linker_resolved_cross_file",
                            name=entity_name,
                            original=original_name,
                            target=target_id,
                        )
                        resolved_edges.append(edge)
                    else:
                        fallback = f"{module_path}::Function::{original_name}::1"
                        edge.target_id = fallback
                        self._pending_edges.append((edge, original_name, module_path))
                        log.info(
                            "linker_cross_file_pending",
                            name=entity_name,
                            original=original_name,
                            target=fallback,
                        )
                elif entity_name in import_map:
                    # Handle cases where the entity itself is the imported module
                    module_path, original_name = import_map[entity_name]
                    target_id = await self._resolve_cross_file(
                        original_name,
                        module_path,
                    )
                    if target_id:
                        edge.target_id = target_id
                        resolved_edges.append(edge)
                    else:
                        fallback = f"{module_path}::File::{original_name}::1"
                        edge.target_id = fallback
                        self._pending_edges.append((edge, original_name, module_path))
                else:
                    resolved_edges.append(edge)
            else:
                resolved_edges.append(edge)

        if resolved_edges:
            await self._store.upsert_edges(resolved_edges)

        log.info("ingest_complete", file=document.file_path, resolved=len(resolved_edges))

    async def _resolve_cross_file(
        self,
        entity_name: str,
        module_path: str,
    ) -> str | None:
        """Look up the actual node ID for a cross-file reference."""
        log.info("resolving_cross_file", entity=entity_name, module=module_path)
        candidates = await self._store.find_nodes(name=entity_name)
        log.info("resolve_candidates", count=len(candidates))
        if not candidates:
            return None

        if not module_path:
            return candidates[0].id

        import os
        module_stem = module_path.split("/")[-1]

        for n in candidates:
            if n.file_path == module_path:
                log.info("resolve_match_exact", id=n.id)
                return n.id
            
            filename = os.path.splitext(os.path.basename(n.file_path))[0]
            if filename == module_stem:
                log.info("resolve_match_stem", id=n.id, filename=filename, stem=module_stem)
                return n.id

        return candidates[0].id

        # Get the base name of the module (e.g., 'core' from 'project/core')
        module_stem = module_path.split("/")[-1]

        for n in candidates:
            # Exact match of file path
            if n.file_path == module_path:
                return n.id
            
            # Match filename without extension
            # e.g., '/path/to/core.rs' -> 'core'
            import os
            filename = os.path.splitext(os.path.basename(n.file_path))[0]
            if filename == module_stem:
                return n.id

        return candidates[0].id

    async def resolve_pending_edges(self) -> int:
        """Re-attempt cross-file edges that were deferred."""
        if not self._pending_edges:
            return 0

        fixed = 0
        still_pending: list[tuple[GraphEdge, str, str]] = []
        resolved: list[GraphEdge] = []
        for edge, original_name, module_path in self._pending_edges:
            real_id = await self._resolve_cross_file(original_name, module_path)
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
            await self._store.upsert_edges(resolved)

        self._pending_edges = still_pending
        if fixed:
            log.info("resolve_pending_complete", fixed=fixed, remaining=len(still_pending))
        return fixed

    async def remove_document(self, file_path: str) -> None:
        await self._store.delete_nodes_by_file(file_path)
