from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from google import genai

from vibecoder.smp.memory import SMPMemory


class VibeCoderAgent:
    def __init__(self, workspace: str | Path = ".") -> None:
        self.workspace = Path(workspace).resolve()
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.memory = SMPMemory(workspace=self.workspace)

    def run_vibe_loop(self, prompt: str, current_file: str) -> str:
        file_path = str((self.workspace / current_file).resolve())
        target = Path(file_path)
        if not target.exists():
            raise FileNotFoundError(f"Target file not found: {current_file}")

        source_text = target.read_text(encoding="utf-8")
        compressed_context = self.memory.get_compressed_context(file_path)
        similar = self.memory.semantic_search(prompt, n_results=8)
        semantic_matches = self._format_semantic_matches(similar)

        system_prompt = self._build_system_prompt(
            user_prompt=prompt,
            file_path=file_path,
            source_text=source_text,
            compressed_context=compressed_context,
            semantic_matches=semantic_matches,
        )

        response = self.client.models.generate_content(
            model="gemini-3-pro",
            contents=system_prompt,
        )
        output = (response.text or "").strip()
        if not output:
            raise RuntimeError("Gemini returned empty response for coding loop.")
        return output

    def _format_semantic_matches(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0] if "distances" in result else []

        formatted: list[dict[str, Any]] = []
        for idx, item_id in enumerate(ids):
            formatted.append(
                {
                    "id": item_id,
                    "summary": docs[idx] if idx < len(docs) else "",
                    "metadata": metas[idx] if idx < len(metas) else {},
                    "distance": distances[idx] if idx < len(distances) else None,
                }
            )
        return formatted

    def _build_system_prompt(
        self,
        user_prompt: str,
        file_path: str,
        source_text: str,
        compressed_context: dict[str, Any],
        semantic_matches: list[dict[str, Any]],
    ) -> str:
        return (
            "You are VibeCoder, a senior autonomous coding agent.\n"
            "You must return ONLY Aider-style SEARCH/REPLACE blocks.\n"
            "Rules:\n"
            "1) Preserve formatting and indentation exactly.\n"
            "2) Use minimal diffs.\n"
            "3) Do not emit commentary or markdown fences.\n"
            "4) If multiple edits are required, emit multiple SEARCH/REPLACE blocks.\n\n"
            f"User Request:\n{user_prompt}\n\n"
            f"Target File: {file_path}\n"
            f"Current Source:\n{source_text}\n\n"
            "SMP Compressed Graph Context (JSON):\n"
            f"{json.dumps(compressed_context, indent=2)}\n\n"
            "Semantically Related Nodes:\n"
            f"{json.dumps(semantic_matches, indent=2)}\n"
        )
