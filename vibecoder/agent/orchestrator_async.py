from __future__ import annotations

import inspect
import json
import traceback
from collections.abc import AsyncIterator
from typing import Any

from google import genai
from rich.live import Live
from rich.markdown import Markdown

from vibecoder.agent.tools_async import AsyncAgentTools
from vibecoder.context import AppContext
from vibecoder.smp.memory import SMPMemory


class AsyncAgent:
    """Async ReAct orchestrator with streaming tokens and auto-healing tool loop."""

    def __init__(self, app_context: AppContext, memory: SMPMemory | None = None) -> None:
        self.context = app_context
        self.memory = memory or SMPMemory(app_context)
        self.client = genai.Client(api_key=app_context.config.gemini_api_key).aio
        self.tools = AsyncAgentTools(app_context=app_context, memory=self.memory)
        self.history: list[dict[str, Any]] = []
        self.max_context_tokens = 24_000

    async def chat_stream(self, user_input: str, *, model: str = "gemini-2.5-pro", max_steps: int = 30) -> AsyncIterator[str]:
        self.history.append({"role": "user", "parts": [{"text": user_input}]})

        for _ in range(max_steps):
            running_text = ""
            tool_calls: list[dict[str, Any]] = []
            model_parts: list[dict[str, Any]] = []
            status = "[dim]Thinking...[/dim]"

            with Live(Markdown(status), console=self.context.console, refresh_per_second=20) as live:
                stream_or_coro = self.client.models.generate_content_stream(
                    model=model,
                    contents=self._trimmed_history(),
                    config={
                        "tools": [
                            self.tools.search_codebase,
                            self.tools.explore_graph,
                            self.tools.apply_edit,
                        ]
                    },
                )
                stream = await stream_or_coro if inspect.isawaitable(stream_or_coro) else stream_or_coro

                async for chunk in stream:
                    text_piece = self._extract_text(chunk)
                    if text_piece:
                        running_text += text_piece
                        live.update(Markdown(running_text))
                        yield text_piece

                    for call in self._extract_function_calls(chunk):
                        tool_calls.append(call)
                        model_parts.append({"function_call": {"name": call["name"], "args": call["args"]}})

                if tool_calls:
                    live.update(Markdown(f"[bold yellow]Executing tool: {tool_calls[0]['name']}...[/bold yellow]"))

            if tool_calls:
                if running_text.strip():
                    model_parts.insert(0, {"text": running_text})
                self.history.append({"role": "model", "parts": model_parts})

                tool_responses: list[dict[str, Any]] = []
                for call in tool_calls:
                    name = call["name"]
                    args = call["args"]
                    try:
                        result = await self._execute_tool(name, args)
                        payload: dict[str, Any] = {"ok": True, "result": result}
                    except Exception as exc:
                        payload = {
                            "ok": False,
                            "error": str(exc),
                            "traceback": traceback.format_exc(),
                            "guidance": "Fix the tool arguments/search block and call the tool again.",
                        }

                    tool_responses.append(
                        {
                            "function_response": {
                                "name": name,
                                "response": payload,
                            }
                        }
                    )

                self.history.append({"role": "user", "parts": tool_responses})
                continue

            final_text = running_text.strip() or "Completed with no textual output."
            self.history.append({"role": "model", "parts": [{"text": final_text}]})
            break

    async def _execute_tool(self, name: str, args: dict[str, Any]) -> str:
        if name == "search_codebase":
            return await self.tools.search_codebase(**args)
        if name == "explore_graph":
            return await self.tools.explore_graph(**args)
        if name == "apply_edit":
            return await self.tools.apply_edit(**args)
        raise ValueError(f"Unknown tool requested: {name}")

    def _trimmed_history(self) -> list[dict[str, Any]]:
        system = {"role": "user", "parts": [{"text": self._system_prompt()}]}
        if self._estimate_tokens(json.dumps(self.history, ensure_ascii=False)) <= self.max_context_tokens:
            return [system, *self.history]

        kept: list[dict[str, Any]] = []
        running = self._estimate_tokens(json.dumps(system, ensure_ascii=False))
        for message in reversed(self.history):
            msg_tokens = self._estimate_tokens(json.dumps(message, ensure_ascii=False))
            if running + msg_tokens > self.max_context_tokens:
                continue
            kept.append(message)
            running += msg_tokens

        kept.reverse()
        return [system, *kept]

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        # Practical heuristic: ~4 characters/token on average English + code mix.
        return max(1, len(text) // 4)

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
        return "".join(chunks)

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
            "You are VibeCoder, a principal-level autonomous coding agent. "
            "Operate in a ReAct loop, gather context before editing, and use tools deliberately. "
            "When tool execution fails, repair your plan and retry with corrected arguments."
        )
