from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from vibecoder.agent.fuzzy_editor import EditFailedException, apply_edit_fuzzy
from vibecoder.agent.tools_async import tool
from vibecoder.smp.memory import SMPMemory
from vibecoder.smp.parser import ASTParser
from vibecoder.swarm.sandbox import run_command


class SwarmTools:
    """Async tool surface for swarm worker agents."""

    def __init__(self, workspace: Path, memory: SMPMemory) -> None:
        self.workspace = workspace.resolve()
        self.memory = memory
        self.parser = ASTParser()

    @tool
    async def read_file(self, filepath: str) -> str:
        path = self._resolve_workspace_file(filepath, must_exist=True)
        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        numbered = "\n".join(f"{idx + 1:4d}: {line}" for idx, line in enumerate(text.splitlines()))
        return json.dumps({"ok": True, "filepath": filepath, "content": numbered})

    @tool
    async def explore_graph(self, entity_name: str) -> str:
        query = entity_name.lower().strip()
        matches: list[dict[str, object]] = []

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
    async def edit_and_verify(
        self,
        filepath: str,
        search_block: str,
        replace_block: str,
        verification_cmd: str,
    ) -> str:
        path = self._resolve_workspace_file(filepath, must_exist=True)
        original = await asyncio.to_thread(path.read_text, encoding="utf-8")
        updated = apply_edit_fuzzy(original, search_block, replace_block)
        if updated == original:
            raise EditFailedException("Edit produced no changes; refine SEARCH/REPLACE blocks.")

        await asyncio.to_thread(self._atomic_write, path, updated)
        parsed_nodes = await asyncio.to_thread(self.parser.parse_file, path)
        await asyncio.to_thread(self.memory.replace_file_nodes, str(path), parsed_nodes)

        result = await run_command(verification_cmd)
        if result["exit_code"] == 0:
            await asyncio.to_thread(self.memory.enrich_nodes, 4)
            return "Success"

        await asyncio.to_thread(self._atomic_write, path, original)
        reverted_nodes = await asyncio.to_thread(self.parser.parse_file, path)
        await asyncio.to_thread(self.memory.replace_file_nodes, str(path), reverted_nodes)
        return str(result["stderr"] or result["stdout"] or "Verification command failed.")

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
