from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from vibecoder.context import AppContext
from vibecoder.smp.memory import SMPMemory
from vibecoder.smp.parser import ASTParser


class AgentTools:
    """Tool surface exposed to Gemini function calling."""

    def __init__(self, app_context: AppContext, memory: SMPMemory) -> None:
        self.context = app_context
        self.workspace = app_context.config.workspace_dir.resolve()
        self.memory = memory
        self.parser = ASTParser()
        self.edited_files: set[str] = set()

    def search_codebase(self, query: str) -> str:
        """Searches ChromaDB semantic memory for files and symbols relevant to a query."""
        result = self.memory.semantic_search(query=query, n_results=8)
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

    def explore_graph(self, entity_name: str) -> str:
        """Returns graph neighbors for symbols/files matching the provided entity name."""
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

    def read_file(self, filepath: str) -> str:
        """Reads a workspace file and returns numbered lines for precise edit planning."""
        path = self._resolve_workspace_file(filepath, must_exist=True)
        text = path.read_text(encoding="utf-8")
        numbered = "\n".join(f"{idx + 1:4d}: {line}" for idx, line in enumerate(text.splitlines()))
        return json.dumps({"ok": True, "filepath": str(path), "content": numbered})

    def apply_edit(self, filepath: str, search_block: str, replace_block: str) -> str:
        """Applies a single exact-match edit using atomic writes and graph re-indexing."""
        path = self._resolve_workspace_file(filepath, must_exist=True)
        if not search_block:
            raise ValueError("search_block cannot be empty.")

        original = path.read_text(encoding="utf-8")
        count = original.count(search_block)
        if count == 0:
            raise ValueError("search_block was not found in the target file.")
        if count > 1:
            raise ValueError("search_block matched multiple locations; edit is ambiguous.")

        updated = original.replace(search_block, replace_block, 1)
        if updated != original:
            self._atomic_write(path, updated)
            parsed_nodes = self.parser.parse_file(path)
            self.memory.replace_file_nodes(str(path), parsed_nodes)
            self.memory.enrich_nodes(batch_size=4)
            self.edited_files.add(str(path))

        return "Success"

    def _resolve_workspace_file(self, filepath: str, must_exist: bool) -> Path:
        candidate = (self.workspace / filepath).resolve()
        if self.workspace not in candidate.parents and candidate != self.workspace:
            raise ValueError("filepath escapes the workspace boundary.")
        if must_exist and not candidate.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        return candidate

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            handle.write(content)
            temp_path = Path(handle.name)
        temp_path.replace(path)
