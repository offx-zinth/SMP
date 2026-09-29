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

    Missing files fail fast up front: invalidating a deleted path walks
    the whole edge index, which costs tens of seconds on kernel-scale
    graphs for no benefit.
    """
    p = msgspec.convert(params, UpdateParams)
    graph = ctx["graph"]

    file_path = p.file_path

    if not _is_path_allowed(file_path):
        log.warning("memory_update_path_forbidden", path=file_path)
        return {"file_path": file_path, "nodes": 0, "edges": 0, "errors": 1, "error": "path_forbidden"}

    if not Path(file_path).is_file():
        return {"file_path": file_path, "nodes": 0, "edges": 0, "errors": 1, "error": "file_not_found"}

    previously_parsed = False
    if hasattr(graph, "get_parse_status"):
        try:
            previously_parsed = bool((await graph.get_parse_status(file_path)).parsed)
        except Exception:  # noqa: BLE001
            previously_parsed = False

    if hasattr(graph, "invalidate_file"):
        try:
            # enqueue=False: this handler re-parses synchronously below, so a
            # background task would only redo the same work on the event loop.
            await graph.invalidate_file(file_path, enqueue=False)
        except TypeError:
            try:  # Alternate backends without the enqueue flag.
                await graph.invalidate_file(file_path)
            except Exception:  # noqa: BLE001
                log.debug("invalidate_failed", file_path=file_path)
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
        stale_marked = 0
        if previously_parsed and nodes and hasattr(graph, "upsert_node"):
            stale_marked = await _mark_nodes_stale(graph, nodes)
        return {
            "file_path": file_path,
            "nodes": len(nodes),
            "edges": await _count_file_edges(graph, nodes),
            "errors": 0,
            "stale_marked": stale_marked,
        }

    if hasattr(graph, "parse_file"):
        try:
            nodes = await graph.parse_file(file_path)
        except FileNotFoundError:
            return {"file_path": file_path, "nodes": 0, "edges": 0, "errors": 1, "error": "file_not_found"}
        except Exception as exc:  # noqa: BLE001
            log.warning("parse_failed", file_path=file_path, error=str(exc))
            return {"file_path": file_path, "nodes": 0, "edges": 0, "errors": 1, "error": str(exc)}
        stale_marked = 0
        if previously_parsed and nodes and hasattr(graph, "upsert_node"):
            stale_marked = await _mark_nodes_stale(graph, nodes)
        return {
            "file_path": file_path,
            "nodes": len(nodes),
            "edges": await _count_file_edges(graph, nodes),
            "errors": 0,
            "stale_marked": stale_marked,
        }

    return {
        "file_path": file_path,
        "nodes": 0,
        "edges": 0,
        "errors": 0,
        "message": "graph store does not support live parsing",
    }


async def _count_file_edges(graph: Any, nodes: list[Any]) -> int:
    """Count in/out edges for *nodes* so smp/update reports real edge churn."""
    total = 0
    for node in nodes:
        node_id = getattr(node, "id", "")
        if not node_id:
            continue
        try:
            edges = await graph.get_edges(node_id, direction="both")
        except Exception:  # noqa: BLE001
            continue
        total += len(edges)
    return total


def _stale_copy(node: Any) -> Any | None:
    """Return a copy of *node* with semantic status ``stale``, if applicable."""
    try:
        semantic = node.semantic
    except AttributeError:
        return None
    if getattr(semantic, "status", "") == "stale":
        return None
    try:
        return msgspec.structs.replace(node, semantic=msgspec.structs.replace(semantic, status="stale"))
    except Exception:  # noqa: BLE001
        return None


async def _mark_nodes_stale(graph: Any, nodes: list[Any]) -> int:
    """Flag re-parsed nodes stale so ``smp/enrich/stale`` picks them up.

    Re-parsing rebuilds nodes with default semantics, silently dropping the
    signal that their content changed since they were enriched. Marking
    them ``stale`` restores that signal.
    """
    marked = 0
    for node in nodes:
        updated = _stale_copy(node)
        if updated is None:
            continue
        try:
            await graph.upsert_node(updated)
        except Exception:  # noqa: BLE001
            continue
        marked += 1
    return marked


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
                **await _summarise_scope(graph, scope_path),
                "queued": queued,
            }

    return {"status": "reindex_requested", "scope": rp.scope}


_SCAN_LIMIT = 5000


async def _summarise_scope(graph: Any, scope_path: Path) -> dict[str, Any]:
    """Count parseable files under *scope_path* and how many lack parse status.

    Gives ``smp/reindex`` callers an answer to "is my scope indexed?" without
    parsing anything. The walk is capped so huge scopes stay cheap.
    """
    from smp.store.graph.parser import _EXTENSION_TO_LANGUAGE

    parseable = 0
    unparsed = 0
    truncated = False
    can_status = hasattr(graph, "get_parse_status")
    for root, _dirs, files in os.walk(scope_path):
        for name in files:
            if Path(name).suffix.lower() not in _EXTENSION_TO_LANGUAGE:
                continue
            parseable += 1
            if parseable >= _SCAN_LIMIT:
                truncated = True
                break
            if not can_status:
                continue
            try:
                status = await graph.get_parse_status(str(Path(root) / name))
            except Exception:  # noqa: BLE001
                unparsed += 1
            else:
                if not status.parsed:
                    unparsed += 1
        if truncated:
            break
    return {"scope_files": parseable, "unparsed_files": unparsed, "scan_truncated": truncated}
