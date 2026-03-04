from __future__ import annotations

import logging
from pathlib import Path

from rich.logging import RichHandler


def setup_logger(level: str, *, log_dir: Path | None = None) -> None:
    """Configure application logging.

    INFO and above are shown in the console with Rich formatting, while DEBUG and above are
    persisted to `.vibecoder/vibe.log`.
    """

    resolved_log_dir = (log_dir or Path(".vibecoder")).resolve()
    resolved_log_dir.mkdir(parents=True, exist_ok=True)
    log_file = resolved_log_dir / "vibe.log"

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.DEBUG)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    console_handler = RichHandler(rich_tracebacks=True, show_path=False)
    console_handler.setLevel(level.upper())
    console_handler.setFormatter(logging.Formatter("%(message)s"))

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
