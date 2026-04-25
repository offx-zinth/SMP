"""Centralised settings for the SMP graph engine.

Reads configuration from environment variables (with sensible defaults) so
the same defaults apply across the CLI, the JSON-RPC server, and any
embedded usage of the graph store.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Runtime configuration for SMP.

    Defaults match those described in ``SPEC.md`` (``.smp/graph.smpg``,
    ``.smp/smp.smpv``).  All fields can be overridden via environment
    variables when ``Settings.from_env`` is used.
    """

    graph_path: str = ".smp/graph.smpg"
    vector_path: str = ".smp/smp.smpv"
    host: str = "0.0.0.0"
    port: int = 8420

    @classmethod
    def from_env(cls) -> Settings:
        """Build a ``Settings`` instance from environment variables.

        Environment variables consulted (with their defaults shown):

        * ``SMP_GRAPH_PATH``  – ``.smp/graph.smpg``
        * ``SMP_VECTOR_PATH`` – ``.smp/smp.smpv``
        * ``SMP_HOST``        – ``0.0.0.0``
        * ``SMP_PORT``        – ``8420``
        """
        port_value = os.environ.get("SMP_PORT")
        try:
            port = int(port_value) if port_value else 8420
        except ValueError:
            port = 8420

        return cls(
            graph_path=os.environ.get("SMP_GRAPH_PATH", ".smp/graph.smpg"),
            vector_path=os.environ.get("SMP_VECTOR_PATH", ".smp/smp.smpv"),
            host=os.environ.get("SMP_HOST", "0.0.0.0"),
            port=port,
        )


__all__ = ["Settings"]
