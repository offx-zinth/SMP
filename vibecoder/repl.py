from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Iterable

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.lexers import PygmentsLexer
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.styles import Style
from pygments.lexers.markup import MarkdownLexer
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.spinner import Spinner

from vibecoder.agent.orchestrator import AgentOrchestrator
from vibecoder.smp.memory import SMPMemory
from vibecoder.smp.parser import ASTParser, ParsedNode
from vibecoder.utils.git_utils import GitSafetyManager

console = Console()


class VibeRepl:
    def __init__(self, workspace: str | Path = ".") -> None:
        self.workspace = Path(workspace).resolve()
        self.orchestrator = AgentOrchestrator(workspace=self.workspace)
        self.git = GitSafetyManager(workspace=self.workspace)
        self.parser = ASTParser()

    def run(self) -> None:
        if "GEMINI_API_KEY" not in os.environ:
            console.print("[red]GEMINI_API_KEY is not set.[/red]")
            return

        session = PromptSession(multiline=True, key_bindings=self._key_bindings())
        style = Style.from_dict({"prompt": "ansicyan bold"})

        console.print("[bold green]VibeCoder REPL[/bold green] — commands: /exit /undo /refresh")

        while True:
            with patch_stdout():
                text = session.prompt(
                    [("class:prompt", "(vibe)> ")],
                    style=style,
                    complete_style=CompleteStyle.MULTI_COLUMN,
                    lexer=PygmentsLexer(MarkdownLexer),
                ).strip()

            if not text:
                continue
            if text == "/exit":
                break
            if text == "/undo":
                console.print(f"[yellow]{self.git.undo_last_commit()}[/yellow]")
                continue
            if text == "/refresh":
                self._refresh_index()
                continue

            with Live(Spinner("dots", text="Agent thinking..."), refresh_per_second=12, console=console):
                result = asyncio.run(self.orchestrator.run_turn(text))

            console.print(Markdown(result.final_response))
            if result.edited_files:
                commit_result = self.git.commit_edits(result.edited_files)
                console.print(f"[green]{commit_result}[/green]")

    def _refresh_index(self) -> None:
        memory = SMPMemory(workspace=self.workspace)
        memory.graph.clear()
        memory.save_graph()
        try:
            memory.chroma_client.delete_collection("smp_semantics")
        except Exception:
            pass
        memory.collection = memory.chroma_client.get_or_create_collection("smp_semantics")

        files = _scan_source_files(self.workspace)
        parsed_nodes = _parse_many(self.parser, files)
        memory.build_graph(parsed_nodes)
        enriched = memory.enrich_nodes()
        console.print(f"[green]Refreshed index: {len(files)} files, {len(parsed_nodes)} nodes, {enriched} enriched.[/green]")

    @staticmethod
    def _key_bindings() -> KeyBindings:
        kb = KeyBindings()

        @kb.add("escape", "enter")
        def _(event) -> None:  # type: ignore[no-untyped-def]
            event.current_buffer.validate_and_handle()

        return kb


def _scan_source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    skip_dirs = {".git", ".venv", "venv", "node_modules", ".next", "dist", "build"}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in skip_dirs]
        current = Path(dirpath)
        for filename in filenames:
            path = current / filename
            if path.suffix.lower() in {".py", ".ts", ".tsx", ".js", ".jsx"}:
                files.append(path)

    return files


def _parse_many(parser: ASTParser, files: Iterable[Path]) -> list[ParsedNode]:
    parsed: list[ParsedNode] = []
    for file_path in files:
        try:
            parsed.extend(parser.parse_file(file_path))
        except Exception as exc:
            console.print(f"[yellow]Skipping {file_path}: {exc}[/yellow]")
    return parsed
