from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

from vibecoder.agent.fuzzy_editor import EditFailedException, apply_edit_fuzzy
from vibecoder.context import AppContext
from vibecoder.smp.memory import SMPMemory
from vibecoder.smp.parser import ASTParser

F = TypeVar("F", bound=Callable[..., Awaitable[str]])


def tool(func: F) -> F:
    """Marks a coroutine as an agent tool for function-calling registration."""
    setattr(func, "_vibecoder_tool", True)
    return func


class AsyncAgentTools:
    """Async tool surface exposed to Gemini function calling."""

    def __init__(self, app_context: AppContext, memory: SMPMemory) -> None:
        self.context = app_context
        self.workspace = app_context.config.workspace_dir.resolve()
        self.memory = memory
        self.parser = ASTParser()
        self.edited_files: set[str] = set()

    @tool
    async def search_codebase(self, query: str) -> str:
        result = await asyncio.to_thread(self.memory.semantic_search, query, 8)
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        matches: list[dict[str, Any]] = []

        for idx, node_id in enumerate(ids):
            matches.append(
                {
                    "id": node_id,
                    "summary": docs[idx] if idx < len(docs) else "",
                    "metadata": metadatas[idx] if idx < len(metadatas) else {},
                }
            )

        return json.dumps({"ok": True, "matches": matches}, indent=2)

    @tool
    async def explore_graph(self, entity_name: str) -> str:
        query = entity_name.lower().strip()
        matches: list[dict[str, Any]] = []

        for node_id, attrs in self.memory.graph.nodes(data=True):
            name = str(attrs.get("name", "")).lower()
            file_path = str(attrs.get("file_path", "")).lower()
            if query not in node_id.lower() and query not in name and query not in file_path:
                continue

            outgoing = [
                {"target": target, "relation": edge.get("relation", "UNKNOWN")}
                for _, target, edge in self.memory.graph.out_edges(node_id, data=True)
            ]
            incoming = [
                {"source": source, "relation": edge.get("relation", "UNKNOWN")}
                for source, _, edge in self.memory.graph.in_edges(node_id, data=True)
            ]
            matches.append(
                {
                    "id": node_id,
                    "type": attrs.get("type"),
                    "name": attrs.get("name"),
                    "file_path": attrs.get("file_path"),
                    "incoming": incoming,
                    "outgoing": outgoing,
                }
            )
            if len(matches) >= 12:
                break

        return json.dumps({"ok": True, "matches": matches}, indent=2)

    @tool
    async def apply_edit(self, filepath: str, search_block: str, replace_block: str) -> str:
        path = self._resolve_workspace_file(filepath, must_exist=True)
        original = await asyncio.to_thread(path.read_text, encoding="utf-8")
        updated = apply_edit_fuzzy(original, search_block, replace_block)

        if updated == original:
            raise EditFailedException("Edit produced no changes; refine SEARCH/REPLACE blocks.")

        await asyncio.to_thread(self._atomic_write, path, updated)
        parsed_nodes = await asyncio.to_thread(self.parser.parse_file, path)
        await asyncio.to_thread(self.memory.replace_file_nodes, str(path), parsed_nodes)
        await asyncio.to_thread(self.memory.enrich_nodes, 4)
        self.edited_files.add(str(path))

        return (
            f"Applied fuzzy edit to {path}. "
            f"Reindexed {len(parsed_nodes)} node(s) and refreshed semantic embeddings."
        )

    def _resolve_workspace_file(self, filepath: str, must_exist: bool) -> Path:
        candidate = (self.workspace / filepath).resolve()
        if self.workspace not in candidate.parents and candidate != self.workspace:
            raise ValueError("filepath escapes workspace boundary.")
        if must_exist and not candidate.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        return candidate

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            handle.write(content)
            tmp = Path(handle.name)
        tmp.replace(path)
