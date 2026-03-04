from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google import genai

from vibecoder.agent.tools import ToolRegistry


@dataclass
class AgentTurnResult:
    final_response: str
    edited_files: list[str]


class AgentOrchestrator:
    """Interactive ReAct orchestrator with Gemini function-calling tools."""

    def __init__(self, workspace: str | Path = ".") -> None:
        self.workspace = Path(workspace).resolve()
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.tools = ToolRegistry(workspace=self.workspace)
        self._history: list[dict[str, Any]] = []

    async def run_turn(self, user_prompt: str, max_steps: int = 20) -> AgentTurnResult:
        self._history.append({"role": "user", "parts": [{"text": user_prompt}]})
        edited_files: set[str] = set()

        for _ in range(max_steps):
            response = await asyncio.to_thread(self._call_model)
            calls = self._extract_function_calls(response)
            if not calls:
                text = self._extract_text(response).strip()
                if not text:
                    text = "Completed with no textual summary from model."
                self._history.append({"role": "model", "parts": [{"text": text}]})
                return AgentTurnResult(final_response=text, edited_files=sorted(edited_files))

            model_parts: list[dict[str, Any]] = []
            tool_parts: list[dict[str, Any]] = []
            for call in calls:
                name = call["name"]
                args = call["args"]
                model_parts.append({"function_call": {"name": name, "args": args}})
                result = await asyncio.to_thread(self.tools.execute, name, args)
                if name == "edit_file":
                    try:
                        payload = json.loads(result)
                        if payload.get("ok"):
                            edited_files.add(str(Path(payload.get("filepath", "")).resolve()))
                    except Exception:
                        pass
                tool_parts.append(
                    {
                        "function_response": {
                            "name": name,
                            "response": {"result": result},
                        }
                    }
                )

            self._history.append({"role": "model", "parts": model_parts})
            self._history.append({"role": "user", "parts": tool_parts})

        return AgentTurnResult(
            final_response="Stopped after reaching tool-step limit without final answer.",
            edited_files=sorted(edited_files),
        )

    def _call_model(self) -> Any:
        return self.client.models.generate_content(
            model="gemini-3-pro",
            contents=[
                {"role": "user", "parts": [{"text": self._system_prompt()}]},
                *self._history,
            ],
            config={"tools": [{"function_declarations": self.tools.declarations}]},
        )

    @staticmethod
    def _extract_text(response: Any) -> str:
        direct = getattr(response, "text", None)
        if direct:
            return str(direct)

        texts: list[str] = []
        for candidate in getattr(response, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", []) or []:
                text = getattr(part, "text", None)
                if text:
                    texts.append(str(text))
        return "\n".join(texts)

    @staticmethod
    def _extract_function_calls(response: Any) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        for candidate in getattr(response, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", []) or []:
                fn = getattr(part, "function_call", None)
                if not fn:
                    continue
                name = getattr(fn, "name", None)
                args = getattr(fn, "args", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                if name:
                    calls.append({"name": str(name), "args": args if isinstance(args, dict) else {}})
        return calls

    def _system_prompt(self) -> str:
        return (
            "You are VibeCoder, an expert software engineering agent. "
            "Use tools aggressively and iteratively before editing code. "
            "Typical flow: semantic search or graph exploration, then file reads, then precise edits. "
            "When a tool returns an error, reason and try a better tool call. "
            "After all edits, provide a concise final summary for the user."
        )
