from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.markdown import Markdown
from rich.status import Status

from vibecoder.agent.orchestrator import AgentOrchestrator
from vibecoder.context import AppContext
from vibecoder.smp.memory import SMPMemory
from vibecoder.smp.parser import ASTParser, ParsedNode
from vibecoder.utils.git_utils import GitManager


class VibeRepl:
    """Interactive dashboard for VibeCoder chat sessions."""

    def __init__(self, app_context: AppContext, orchestrator: AgentOrchestrator, memory: SMPMemory) -> None:
        self.context = app_context
        self.console: Console = app_context.console
        self.orchestrator = orchestrator
        self.memory = memory
        self.git = GitManager(app_context)
        self.parser = ASTParser()

    def run(self) -> None:
        if not self.context.config.gemini_api_key:
            self.console.print("[red]Missing Gemini API key.[/red]")
            return

        session = PromptSession(multiline=True, key_bindings=self._build_key_bindings())
        self.console.print("[bold green]VibeCoder[/bold green] ready. Commands: /exit /undo /refresh")

        while True:
            with patch_stdout():
                prompt = session.prompt("(vibe)> ").strip()
            if not prompt:
                continue

            if prompt == "/exit":
                self.console.print("[cyan]Goodbye.[/cyan]")
                break
            if prompt == "/undo":
                self.console.print(f"[yellow]{self.git.undo_last_commit()}[/yellow]")
                continue
            if prompt == "/refresh":
                self._refresh_index()
                continue

            with Status("VibeCoder is thinking...", spinner="dots", console=self.console):
                response = self.orchestrator.chat_turn(prompt)
            self.console.print(Markdown(response))

    def _refresh_index(self) -> None:
        with Status("Refreshing SMP memory...", spinner="dots", console=self.console):
            self.memory.graph.clear()
            self.memory.save_graph()
            try:
                self.memory.chroma_client.delete_collection("smp_semantics")
            except Exception:
                pass
            self.memory.collection = self.memory.chroma_client.get_or_create_collection("smp_semantics")

            files = _scan_source_files(self.context.config.workspace_dir)
            parsed_nodes = _parse_many(self.parser, files)
            self.memory.build_graph(parsed_nodes)
            enriched = self.memory.enrich_nodes()

        self.console.print(
            f"[green]Refresh complete: {len(files)} files, {len(parsed_nodes)} nodes, {enriched} summaries.[/green]"
        )

    @staticmethod
    def _build_key_bindings() -> KeyBindings:
        bindings = KeyBindings()

        @bindings.add("escape", "enter")
        def submit(event) -> None:  # type: ignore[no-untyped-def]
            event.current_buffer.validate_and_handle()

        return bindings


def _scan_source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    skip_dirs = {".git", ".venv", "venv", "node_modules", ".next", "dist", "build", "__pycache__"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in skip_dirs]
        for filename in filenames:
            path = Path(dirpath) / filename
            if path.suffix.lower() in {".py", ".ts", ".tsx", ".js", ".jsx"}:
                files.append(path)
    return files


def _parse_many(parser: ASTParser, files: Iterable[Path]) -> list[ParsedNode]:
    parsed_nodes: list[ParsedNode] = []
    for path in files:
        try:
            parsed_nodes.extend(parser.parse_file(path))
        except Exception:
            continue
    return parsed_nodes
