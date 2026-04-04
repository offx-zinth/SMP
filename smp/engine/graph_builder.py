"""Graph builder — maps parsed Documents into the graph store with Global Linking."""

from __future__ import annotations

from smp.core.models import Document, GraphEdge, NodeType
from smp.engine.interfaces import GraphBuilder as GraphBuilderInterface
from smp.logging import get_logger
from smp.store.interfaces import GraphStore

log = get_logger(__name__)


class DefaultGraphBuilder(GraphBuilderInterface):
    def __init__(self, graph_store: GraphStore) -> None:
        self._store = graph_store
        self._pending_edges: list[tuple[GraphEdge, str, str]] = []  # (edge, original_name, module_path)

    async def ingest_document(self, document: Document) -> None:
        # 1. Map local definitions
        name_to_id = {n.name: n.id for n in document.nodes}

        # 2. Map imports (The Global Linker — cross-file resolution)
        #    import_map:  alias_or_name -> (module_path, original_name)
        #    For "from X import foo as bar", maps bar -> (path, foo)
        #    For "from X import foo",        maps foo -> (path, foo)
        import_map: dict[str, tuple[str, str]] = {}
        for node in document.nodes:
            if node.type != NodeType.IMPORT:
                continue
            module_path = node.name.replace(".", "/") + ".py"
            sig = node.signature
            if "import" in sig and sig.strip().startswith("from"):
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
            elif "import" in sig:
                parts = sig.replace("import", "").strip().split(",")
                for p in parts:
                    stripped = p.strip()
                    if " as " in stripped:
                        original, alias = stripped.split(" as ", 1)
                        import_map[alias.strip()] = (module_path, original.strip())
                    else:
                        name = stripped.split()[0]
                        import_map[name] = (module_path, name)

        # 3. Upsert nodes FIRST so store lookups can find them
        if document.nodes:
            await self._store.upsert_nodes(document.nodes)

        # 4. Resolve edges — fix ::0 (unresolved) targets
        resolved_edges: list[GraphEdge] = []
        for edge in document.edges:
            parts = edge.target_id.split("::")
            if len(parts) >= 4 and parts[-1] == "0":
                entity_name = parts[2]

                # OPTION A: defined in the same file
                if entity_name in name_to_id:
                    edge.target_id = name_to_id[entity_name]
                    resolved_edges.append(edge)
                    continue

                # OPTION B: imported from another file — look up actual node
                if entity_name in import_map:
                    module_path, original_name = import_map[entity_name]
                    target_id = await self._resolve_cross_file(
                        original_name, module_path,
                    )
                    if target_id:
                        edge.target_id = target_id
                        log.info(
                            "linker_resolved_cross_file",
                            name=entity_name, original=original_name, target=target_id,
                        )
                        resolved_edges.append(edge)
                    else:
                        # Target file not yet ingested — stash for later
                        fallback = f"{module_path}::FUNCTION::{original_name}::1"
                        edge.target_id = fallback
                        self._pending_edges.append((edge, original_name, module_path))
                        log.info(
                            "linker_cross_file_pending",
                            name=entity_name, original=original_name, target=fallback,
                        )
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
        candidates = await self._store.find_nodes(name=entity_name)
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

    async def resolve_pending_edges(self) -> int:
        """Re-attempt cross-file edges that were deferred because the target
        file had not been ingested yet.

        Returns the number of edges successfully created.
        """
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
                    original=original_name, target=real_id,
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
