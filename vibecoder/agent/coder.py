"""Backward-compatible shim for the orchestrator-driven coding agent."""

from __future__ import annotations

from vibecoder.agent.orchestrator import AgentOrchestrator
from vibecoder.context import AppContext


class VibeCoderAgent:
    def __init__(self, app_context: AppContext) -> None:
        self.orchestrator = AgentOrchestrator(app_context=app_context)

    def run_vibe_loop(self, prompt: str, current_file: str | None = None) -> str:
        scoped_prompt = prompt if current_file is None else f"Target file: {current_file}\n\n{prompt}"
        return self.orchestrator.chat_turn(scoped_prompt)
