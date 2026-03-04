from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console

from vibecoder.config import Config


@dataclass(slots=True)
class AppContext:
    """Holds application-wide runtime state for a CLI invocation."""

    config: Config
    console: Console
    smp_memory: Any | None = None
    agent: Any | None = None

    @classmethod
    def from_config(cls, config: Config) -> "AppContext":
        """Create a context and initialize required filesystem layout."""
        context = cls(config=config, console=Console())
        context.setup()
        return context

    def setup(self) -> None:
        """Prepare filesystem directories required by the application."""
        db_dir = self._resolve_db_dir()
        db_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_db_dir(self) -> Path:
        smp_db_dir = self.config.smp_db_dir
        if smp_db_dir.is_absolute():
            return smp_db_dir
        return self.config.workspace_dir / smp_db_dir
