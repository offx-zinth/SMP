"""Backward-compatible shim for the new orchestrator-driven agent."""

from __future__ import annotations

import asyncio
from pathlib import Path

from vibecoder.agent.orchestrator import AgentOrchestrator


class VibeCoderAgent:
    def __init__(self, workspace: str | Path = ".") -> None:
        self.orchestrator = AgentOrchestrator(workspace=workspace)

    def run_vibe_loop(self, prompt: str, current_file: str | None = None) -> str:
        scoped_prompt = prompt if not current_file else f"Target file: {current_file}\n\n{prompt}"
        result = asyncio.run(self.orchestrator.run_turn(scoped_prompt))
        return result.final_response
