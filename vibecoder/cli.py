from __future__ import annotations

from pathlib import Path
from typing import Iterable

import typer
from rich.console import Console
from rich.progress import track

from vibecoder.agent.coder import VibeCoderAgent
from vibecoder.agent.file_editor import AiderStyleEditor
from vibecoder.smp.memory import SMPMemory
from vibecoder.smp.parser import ASTParser, ParsedNode

app = typer.Typer(help="VibeCoder: Local-first AI coding agent")
console = Console()


def _scan_source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    skip_dirs = {".git", ".venv", "venv", "node_modules", ".next", "dist", "build"}

    for dirpath, dirnames, filenames in __import__("os").walk(root):
        dirnames[:] = [name for name in dirnames if name not in skip_dirs]
        current = Path(dirpath)
        for filename in filenames:
            path = current / filename
            if path.suffix.lower() in {".py", ".ts"}:
                files.append(path)

    return files


def _parse_many(parser: ASTParser, files: Iterable[Path]) -> list[ParsedNode]:
    parsed: list[ParsedNode] = []
    for file_path in track(list(files), description="Parsing source files..."):
        try:
            parsed.extend(parser.parse_file(file_path))
        except Exception as exc:
            console.print(f"[yellow]Skipping {file_path}: {exc}[/yellow]")
    return parsed


@app.command("init")
def vibe_init() -> None:
    """Build initial SMP graph + Chroma semantics for current workspace."""
    workspace = Path.cwd()
    parser = ASTParser()
    memory = SMPMemory(workspace=workspace)

    files = _scan_source_files(workspace)
    if not files:
        console.print("[red]No .py or .ts files found.[/red]")
        raise typer.Exit(code=1)

    parsed_nodes = _parse_many(parser, files)
    memory.build_graph(parsed_nodes)
    enriched = memory.enrich_nodes()

    console.print(f"[green]Indexed {len(files)} files, {len(parsed_nodes)} AST nodes.[/green]")
    console.print(f"[green]Enriched {enriched} graph nodes into ChromaDB.[/green]")


@app.command("code")
def vibe_code(file: str, prompt: str) -> None:
    """Generate and apply SEARCH/REPLACE edits for a specific file."""
    workspace = Path.cwd()
    target = (workspace / file).resolve()
    if not target.exists():
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(code=1)

    agent = VibeCoderAgent(workspace=workspace)
    editor = AiderStyleEditor()
    parser = ASTParser()

    console.print("[cyan]Running VibeCoder reasoning loop...[/cyan]")
    model_output = agent.run_vibe_loop(prompt=prompt, current_file=file)

    console.print("[cyan]Applying SEARCH/REPLACE edits...[/cyan]")
    editor.apply_response(target, model_output)

    parsed_nodes = parser.parse_file(target)
    agent.memory.replace_file_nodes(str(target), parsed_nodes)
    agent.memory.enrich_nodes()

    console.print("[green]Edit applied and SMP memory incrementally updated.[/green]")


if __name__ == "__main__":
    app()
