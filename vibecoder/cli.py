from __future__ import annotations

import os
from pathlib import Path

import typer
from git import Repo

from vibecoder.agent.orchestrator import AgentOrchestrator
from vibecoder.config import Config
from vibecoder.context import AppContext
from vibecoder.repl import VibeRepl
from vibecoder.smp.memory import SMPMemory
from vibecoder.smp.parser import ASTParser, ParsedNode
from vibecoder.utils.git_utils import GitManager
from vibecoder.utils.logger import setup_logger

app = typer.Typer(help="VibeCoder: SOTA AI CLI coding agent")


@app.callback()
def main(ctx: typer.Context) -> None:
    """Initialize shared AppContext for command execution."""
    config = Config()
    app_context = AppContext.from_config(config)
    setup_logger(
        config.log_level,
        log_dir=app_context.config.workspace_dir / app_context.config.smp_db_dir,
    )
    ctx.obj = app_context


@app.command()
def init(ctx: typer.Context) -> None:
    """Scan workspace, build SMP graph + semantics, and bootstrap git state."""
    app_context = _require_context(ctx)
    parser = ASTParser()
    memory = SMPMemory(app_context)

    files = _scan_source_files(app_context.config.workspace_dir)
    parsed_nodes = _parse_many(parser, files)
    memory.graph.clear()
    memory.build_graph(parsed_nodes)
    enriched = memory.enrich_nodes()

    git_manager = GitManager(app_context)
    if not git_manager.is_repo():
        Repo.init(app_context.config.workspace_dir)
        git_manager = GitManager(app_context)

    tracked = [str(path) for path in files if path.exists()]
    state_files = [str(memory.graph_path)]
    message = git_manager.commit_changes(
        files=tracked + state_files,
        diff_summary="Initialize VibeCoder SMP memory index and project baseline.",
    )

    app_context.console.print(
        f"[green]Initialized: {len(files)} files, {len(parsed_nodes)} nodes, {enriched} semantic summaries.[/green]"
    )
    app_context.console.print(f"[cyan]{message}[/cyan]")


@app.command()
def chat(ctx: typer.Context) -> None:
    """Launch interactive REPL with orchestrator + SMP memory."""
    app_context = _require_context(ctx)
    if not app_context.config.gemini_api_key or not os.getenv("GEMINI_API_KEY"):
        app_context.console.print("[red]GEMINI_API_KEY is missing from environment.[/red]")
        raise typer.Exit(code=1)

    memory = SMPMemory(app_context)
    orchestrator = AgentOrchestrator(app_context=app_context, memory=memory)
    app_context.smp_memory = memory
    app_context.agent = orchestrator

    repl = VibeRepl(app_context=app_context, orchestrator=orchestrator, memory=memory)
    repl.run()


def _require_context(ctx: typer.Context) -> AppContext:
    obj = ctx.obj
    if not isinstance(obj, AppContext):
        raise RuntimeError("Application context is not initialized.")
    return obj


def _scan_source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    ignore_dirs = {".git", ".venv", "venv", "node_modules", ".next", "dist", "build", "__pycache__"}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in ignore_dirs]
        for filename in filenames:
            path = Path(dirpath) / filename
            if path.suffix.lower() in {".py", ".ts", ".tsx", ".js", ".jsx"}:
                files.append(path)
    return files


def _parse_many(parser: ASTParser, files: list[Path]) -> list[ParsedNode]:
    parsed_nodes: list[ParsedNode] = []
    for path in files:
        try:
            parsed_nodes.extend(parser.parse_file(path))
        except Exception:
            continue
    return parsed_nodes


if __name__ == "__main__":
    app()
