"""Structured logging configuration for SMP.

Usage:
    from smp.logging import get_logger
    log = get_logger(__name__)
    log.info("graph_updated", nodes=42, edges=97)
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(*, json: bool = False, level: str = "INFO") -> None:
    """Initialise structlog + stdlib logging.

    Args:
        json: When True, render as newline-delimited JSON (production).
              When False, render with colours (development).
        level: Minimum log level for the root SMP logger.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if json:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger("smp")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger scoped to *name*."""
    return structlog.get_logger(name)


# Auto-configure with dev defaults on first import.
configure_logging()
