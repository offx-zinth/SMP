from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any

from google import genai

from vibecoder.agent.tools import AgentTools
from vibecoder.context import AppContext
from vibecoder.smp.memory import SMPMemory
from vibecoder.utils.git_utils import GitManager


@dataclass(slots=True)
class ToolCallRecord:
    name: str
    args_json: str
    ok: bool


class ToolHistory:
    """Tracks recent tool calls to prevent repetitive failed loops."""

    def __init__(self) -> None:
        self._records: list[ToolCallRecord] = []

    def append(self, name: str, args: dict[str, Any], ok: bool) -> None:
        self._records.append(ToolCallRecord(name=name, args_json=json.dumps(args, sort_keys=True), ok=ok))

    def repeated_failure(self) -> ToolCallRecord | None:
        if len(self._records) < 2:
            return None
        last = self._records[-1]
        prev = self._records[-2]
        if last.name == prev.name and last.args_json == prev.args_json and not last.ok and not prev.ok:
            return last
        return None


class AgentOrchestrator:
    """Autonomous ReAct loop for Gemini with local tool execution."""

    def __init__(self, app_context: AppContext, memory: SMPMemory | None = None) -> None:
        self.context = app_context
        self.workspace = app_context.config.workspace_dir.resolve()
        self.client = genai.Client(api_key=app_context.config.gemini_api_key)
        self.memory = memory or SMPMemory(app_context)
        self.tools = AgentTools(app_context=app_context, memory=self.memory)
        self.git = GitManager(app_context=app_context)
        self.history: list[dict[str, Any]] = []
        self.tool_history = ToolHistory()

    def chat_turn(self, user_prompt: str, max_steps: int = 24) -> str:
        self.history.append({"role": "user", "parts": [{"text": user_prompt}]})
        edited_before = set(self.tools.edited_files)

        for _ in range(max_steps):
            response = self.client.models.generate_content(
                model="gemini-3-pro",
                contents=[
                    {"role": "user", "parts": [{"text": self._system_prompt()}]},
                    *self.history,
                ],
                config={
                    "tools": [
                        self.tools.search_codebase,
                        self.tools.explore_graph,
                        self.tools.read_file,
                        self.tools.apply_edit,
                    ]
                },
            )

            calls = self._extract_function_calls(response)
            if not calls:
                text = self._extract_text(response).strip() or "Completed with no textual output."
                self.history.append({"role": "model", "parts": [{"text": text}]})

                applied = sorted(self.tools.edited_files - edited_before)
                if applied:
                    self._commit_in_background(applied, diff_summary=text)
                return text

            model_parts: list[dict[str, Any]] = []
            tool_parts: list[dict[str, Any]] = []

            for call in calls:
                tool_name = call["name"]
                args = call["args"]
                model_parts.append({"function_call": {"name": tool_name, "args": args}})
                try:
                    output = self._execute_tool(tool_name, args)
                    payload = {"ok": True, "result": output}
                    self.tool_history.append(tool_name, args, ok=True)
                except Exception as exc:
                    payload = {"ok": False, "error": str(exc)}
                    self.tool_history.append(tool_name, args, ok=False)

                tool_parts.append(
                    {
                        "function_response": {
                            "name": tool_name,
                            "response": payload,
                        }
                    }
                )

                repeated = self.tool_history.repeated_failure()
                if repeated is not None:
                    message = (
                        "Stopping to avoid repetitive failed tool loop: "
                        f"{repeated.name} called twice with same args and failed. "
                        "Please provide additional guidance or refine the task."
                    )
                    self.history.append({"role": "model", "parts": model_parts})
                    self.history.append({"role": "user", "parts": tool_parts})
                    self.history.append({"role": "model", "parts": [{"text": message}]})
                    return message

            self.history.append({"role": "model", "parts": model_parts})
            self.history.append({"role": "user", "parts": tool_parts})

        return "Stopped after reaching tool-loop limit without a final response."

    def _commit_in_background(self, files: list[str], diff_summary: str) -> None:
        if not self.git.is_repo():
            return

        def _commit() -> None:
            self.git.commit_changes(files=files, diff_summary=diff_summary)

        threading.Thread(target=_commit, daemon=True).start()

    def _execute_tool(self, name: str, args: dict[str, Any]) -> str:
        if name == "search_codebase":
            return self.tools.search_codebase(**args)
        if name == "explore_graph":
            return self.tools.explore_graph(**args)
        if name == "read_file":
            return self.tools.read_file(**args)
        if name == "apply_edit":
            return self.tools.apply_edit(**args)
        raise ValueError(f"Unknown tool requested: {name}")

    @staticmethod
    def _extract_text(response: Any) -> str:
        direct = getattr(response, "text", None)
        if direct:
            return str(direct)
        chunks: list[str] = []
        for candidate in getattr(response, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", []) or []:
                text = getattr(part, "text", None)
                if text:
                    chunks.append(str(text))
        return "\n".join(chunks)

    @staticmethod
    def _extract_function_calls(response: Any) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        for candidate in getattr(response, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", []) or []:
                function_call = getattr(part, "function_call", None)
                if function_call is None:
                    continue
                name = str(getattr(function_call, "name", "")).strip()
                raw_args = getattr(function_call, "args", {})
                args: dict[str, Any]
                if isinstance(raw_args, str):
                    args = json.loads(raw_args) if raw_args.strip() else {}
                elif isinstance(raw_args, dict):
                    args = raw_args
                else:
                    args = {}
                if name:
                    calls.append({"name": name, "args": args})
        return calls

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are VibeCoder, an autonomous staff-level coding agent. "
            "Think in a ReAct style and call tools iteratively until you have enough evidence. "
            "Use search_codebase/explore_graph/read_file before apply_edit when possible. "
            "If apply_edit fails with AmbiguousMatchError, expand your SEARCH block with unique surrounding lines. "
            "If the same tool call fails twice in a row, stop and ask the user for clarification. "
            "When edits succeed, summarize exactly what changed and why."
        )
