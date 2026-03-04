from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from vibecoder.agent.file_editor import AiderStyleEditor, FileEditApplyError, SearchReplaceBlock
from vibecoder.smp.memory import SMPMemory
from vibecoder.smp.parser import ASTParser

ToolHandler = Callable[..., str]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


class ToolRegistry:
    """Registry that binds model-callable tools to local implementations."""

    def __init__(self, workspace: str | Path = ".") -> None:
        self.workspace = Path(workspace).resolve()
        self.memory = SMPMemory(workspace=self.workspace)
        self.editor = AiderStyleEditor()
        self.parser = ASTParser()
        self._handlers: dict[str, ToolHandler] = {
            "search_semantic": self.search_semantic,
            "explore_graph": self.explore_graph,
            "read_file": self.read_file,
            "edit_file": self.edit_file,
        }

    @property
    def declarations(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "search_semantic",
                "description": "Semantic code search over indexed summaries in ChromaDB.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "query": {"type": "STRING", "description": "Search query."},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "explore_graph",
                "description": "Explore the SMP graph for an entity and its relationships.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "entity_name": {"type": "STRING", "description": "Entity to inspect."},
                    },
                    "required": ["entity_name"],
                },
            },
            {
                "name": "read_file",
                "description": "Read a file from the workspace with line numbers.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "filepath": {"type": "STRING", "description": "Relative workspace path."},
                    },
                    "required": ["filepath"],
                },
            },
            {
                "name": "edit_file",
                "description": "Apply one exact SEARCH/REPLACE edit to a file.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "filepath": {"type": "STRING", "description": "Relative workspace path."},
                        "search_block": {"type": "STRING", "description": "Exact text to replace."},
                        "replace_block": {"type": "STRING", "description": "Replacement text."},
                    },
                    "required": ["filepath", "search_block", "replace_block"],
                },
            },
        ]

    def execute(self, name: str, args: dict[str, Any]) -> str:
        handler = self._handlers.get(name)
        if handler is None:
            return json.dumps({"ok": False, "error": f"Unknown tool: {name}"})
        try:
            return handler(**args)
        except Exception as exc:  # tool errors are surfaced to model for retry
            return json.dumps({"ok": False, "error": str(exc)})

    def search_semantic(self, query: str) -> str:
        result = self.memory.semantic_search(query=query, n_results=8)
        payload: list[dict[str, Any]] = []
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        for i, item_id in enumerate(ids):
            payload.append(
                {
                    "id": item_id,
                    "summary": docs[i] if i < len(docs) else "",
                    "metadata": metas[i] if i < len(metas) else {},
                }
            )
        return json.dumps({"ok": True, "matches": payload}, indent=2)

    def explore_graph(self, entity_name: str) -> str:
        graph = self.memory.graph
        matched = [
            (node_id, attrs)
            for node_id, attrs in graph.nodes(data=True)
            if entity_name.lower() in str(attrs.get("name", "")).lower()
            or entity_name.lower() in str(attrs.get("file_path", "")).lower()
            or entity_name.lower() in node_id.lower()
        ]
        if not matched:
            return json.dumps({"ok": True, "matches": []}, indent=2)

        response: list[dict[str, Any]] = []
        for node_id, attrs in matched[:12]:
            outgoing = [
                {
                    "target": target,
                    "relation": edge.get("relation", "UNKNOWN"),
                }
                for _, target, edge in graph.out_edges(node_id, data=True)
            ]
            incoming = [
                {
                    "source": source,
                    "relation": edge.get("relation", "UNKNOWN"),
                }
                for source, _, edge in graph.in_edges(node_id, data=True)
            ]
            response.append(
                {
                    "node_id": node_id,
                    "type": attrs.get("type"),
                    "name": attrs.get("name") or attrs.get("file_path"),
                    "file_path": attrs.get("file_path"),
                    "outgoing": outgoing,
                    "incoming": incoming,
                }
            )
        return json.dumps({"ok": True, "matches": response}, indent=2)

    def read_file(self, filepath: str) -> str:
        path = self._resolve_workspace_path(filepath)
        text = path.read_text(encoding="utf-8")
        with_lines = "\n".join(f"{idx + 1:4d}: {line}" for idx, line in enumerate(text.splitlines()))
        return json.dumps({"ok": True, "filepath": str(path), "content": with_lines})

    def edit_file(self, filepath: str, search_block: str, replace_block: str) -> str:
        path = self._resolve_workspace_path(filepath)
        try:
            self.editor.apply_blocks(path, [SearchReplaceBlock(search=search_block, replace=replace_block)])
        except FileEditApplyError as exc:
            return json.dumps({"ok": False, "error": str(exc)})

        parsed = self.parser.parse_file(path)
        self.memory.replace_file_nodes(str(path), parsed)
        self.memory.enrich_nodes(batch_size=4)
        return json.dumps({"ok": True, "filepath": str(path), "message": "Edit applied and memory updated."})

    def _resolve_workspace_path(self, filepath: str) -> Path:
        candidate = (self.workspace / filepath).resolve()
        if self.workspace not in candidate.parents and candidate != self.workspace:
            raise ValueError("File path escapes workspace boundary.")
        if not candidate.exists():
            raise FileNotFoundError(f"File not found: {filepath}")
        return candidate
