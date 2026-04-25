"""Memory management handlers (smp/update, smp/batch_update, smp/reindex).

The ingest-free design routes file updates through ``MMapGraphStore``:
``ensure_parsed`` re-parses on demand, ``invalidate_file`` marks a path
stale, and ``watch_directories`` / ``pre_parse`` drive the background
scheduler.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import msgspec

from smp.core.models import BatchUpdateParams, ReindexParams, UpdateParams
from smp.logging import get_logger

log = get_logger(__name__)


async def update(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/update`` — re-parse a single file via the live graph.

    Missing or unparseable files are tolerated: callers always receive a
    well-formed envelope (with the error count incremented) so the SMP
    protocol behaves the same regardless of which graph backend is in use.
    """
    p = msgspec.convert(params, UpdateParams)
    graph = ctx["graph"]

    file_path = p.file_path

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

    if (
        hasattr(graph, "watch_directories")
        and hasattr(graph, "pre_parse")
        and rp.scope
    ):
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
