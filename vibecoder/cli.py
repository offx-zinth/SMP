from __future__ import annotations

import logging

import typer

from vibecoder.config import Config
from vibecoder.context import AppContext
from vibecoder.utils.logger import setup_logger

app = typer.Typer(help="VibeCoder: SOTA AI CLI coding agent")


@app.callback()
def main(ctx: typer.Context) -> None:
    """Initialize global application context and logging."""
    config = Config()
    app_context = AppContext.from_config(config)
    setup_logger(config.log_level, log_dir=app_context.config.workspace_dir / app_context.config.smp_db_dir)
    ctx.obj = app_context


@app.command()
def init(ctx: typer.Context) -> None:
    """Initialize project chassis resources."""
    _ = ctx.obj
    logging.getLogger(__name__).info("Initializing chassis...")


@app.command()
def chat(ctx: typer.Context) -> None:
    """Start the interactive chat REPL (placeholder)."""
    _ = ctx.obj
    logging.getLogger(__name__).info("Starting REPL...")


if __name__ == "__main__":
    app()
