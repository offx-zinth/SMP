"""Memory management handlers (smp/update, smp/batch_update, smp/reindex).

The ingest-free design routes file updates through ``MMapGraphStore``:
``ensure_parsed`` re-parses on demand, ``invalidate_file`` marks a path
stale, and ``watch_directories`` / ``pre_parse`` drive the background
scheduler.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import msgspec

from smp.core.models import BatchUpdateParams, ReindexParams, UpdateParams
from smp.logging import get_logger

log = get_logger(__name__)


def _is_path_allowed(path: str) -> bool:
    """Check if the given path is within the allowed paths defined by SMP_ALLOWED_PATHS."""
    allowed_env = os.environ.get("SMP_ALLOWED_PATHS")
    if not allowed_env:
        return True  # Default to allow all if not configured, or should I default to block?
        # The prompt says "Add path allowlist validation... Use SMP_ALLOWED_PATHS env var."
        # Usually, if an allowlist is configured, you use it. If not, maybe it's open?
        # In a hardened environment, you'd want it to be strict.
        # But let's see. If I make it block everything by default, it might break things.
        # However, "Security Hardening" suggests it should be strict.
        # Let's assume if SMP_ALLOWED_PATHS is set, we validate. If not, we allow.
        # Wait, usually an allowlist means if it's not on the list, it's not allowed.
        # Let's implement it such that if SMP_ALLOWED_PATHS is set, only those paths are allowed.

    allowed_paths = [p.strip() for p in allowed_env.split(",") if p.strip()]
    resolved_path = Path(path).resolve()
    return any(resolved_path.is_relative_to(Path(allowed).resolve()) for allowed in allowed_paths)


async def update(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/update`` — re-parse a single file via the live graph.

    Missing or unparseable files are tolerated: callers always receive a
    well-formed envelope (with the error count incremented) so the SMP
    protocol behaves the same regardless of which graph backend is in use.
    """
    p = msgspec.convert(params, UpdateParams)
    graph = ctx["graph"]

    file_path = p.file_path

    if not _is_path_allowed(file_path):
        log.warning("memory_update_path_forbidden", path=file_path)
        return {"file_path": file_path, "nodes": 0, "edges": 0, "errors": 1, "error": "path_forbidden"}

    if hasattr(graph, "invalidate_file"):
        try:
            await graph.invalidate_file(file_path)
        except Exception:  # noqa: BLE001
            log.debug("invalidate_failed", file_path=file_path)

    if hasattr(graph, "ensure_parsed"):
        try:
            nodes = await graph.ensure_parsed(file_path)
        except FileNotFoundError:
            return {"file_path": file_path, "nodes": 0, "edges": 0, "errors": 1, "error": "file_not_found"}
        except Exception as exc:  # noqa: BLE001
            log.warning("ensure_parsed_failed", file_path=file_path, error=str(exc))
            return {"file_path": file_path, "nodes": 0, "edges": 0, "errors": 1, "error": str(exc)}
        return {
            "file_path": file_path,
            "nodes": len(nodes),
            "edges": 0,
            "errors": 0,
        }

    if hasattr(graph, "parse_file"):
        try:
            nodes = await graph.parse_file(file_path)
        except FileNotFoundError:
            return {"file_path": file_path, "nodes": 0, "edges": 0, "errors": 1, "error": "file_not_found"}
        except Exception as exc:  # noqa: BLE001
            log.warning("parse_failed", file_path=file_path, error=str(exc))
            return {"file_path": file_path, "nodes": 0, "edges": 0, "errors": 1, "error": str(exc)}
        return {
            "file_path": file_path,
            "nodes": len(nodes),
            "edges": 0,
            "errors": 0,
        }

    return {
        "file_path": file_path,
        "nodes": 0,
        "edges": 0,
        "errors": 0,
        "message": "graph store does not support live parsing",
    }


async def batch_update(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/batch_update`` — re-parse multiple files."""
    bp = msgspec.convert(params, BatchUpdateParams)
    results: list[dict[str, Any]] = []
    for change in bp.changes:
        results.append(await update(change, ctx))
    return {"updates": len(results), "results": results}


async def reindex(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/reindex`` — register a directory with the live watcher."""
    rp = msgspec.convert(params, ReindexParams)
    graph = ctx["graph"]

    if rp.scope and not _is_path_allowed(rp.scope):
        log.warning("memory_reindex_path_forbidden", path=rp.scope)
        return {"status": "error", "scope": rp.scope, "error": "path_forbidden"}

    if hasattr(graph, "watch_directories") and hasattr(graph, "pre_parse") and rp.scope:
        scope_path = Path(rp.scope)
        if scope_path.is_dir():
            graph.watch_directories([scope_path])
            queued = await graph.pre_parse(count=5000)
            return {
                "status": "reindex_started",
                "scope": rp.scope,
                "queued": queued,
            }

    return {"status": "reindex_requested", "scope": rp.scope}
