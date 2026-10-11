"""Query method handlers (smp/navigate, smp/trace, smp/context, ...).

Each handler is a plain ``async def`` accepting ``(params, ctx)`` and
returning a JSON-serialisable dict.  ``ctx`` is expected to provide an
``engine`` (a :class:`~smp.engine.query.DefaultQueryEngine`).
"""

from __future__ import annotations

from typing import Any

import msgspec

from smp.core.models import (
    CodeSnippetParams,
    ContextParams,
    DetectChangesParams,
    FlowParams,
    ImpactParams,
    LocateParams,
    NavigateParams,
    QueryParams,
    SearchParams,
    SemanticSearchParams,
    TraceParams,
)
from smp.logging import get_logger

log = get_logger(__name__)


async def navigate(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/navigate``."""
    normalized = dict(params)
    if "query" not in normalized:
        for alias in ("node_id", "entity", "id", "name"):
            if normalized.get(alias):
                normalized["query"] = normalized[alias]
                break
    p = msgspec.convert(normalized, NavigateParams)
    engine = ctx["engine"]
    return await engine.navigate(p.query, p.include_relationships)  # type: ignore[no-any-return]


async def trace(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/trace``."""
    p = msgspec.convert(params, TraceParams)
    engine = ctx["engine"]
    result = await engine.trace(
        p.start,
        p.relationship,
        p.depth,
        p.direction,
        include_tests=bool(params.get("include_tests", True)),
        risk_labels=bool(params.get("risk_labels", params.get("risk", False))),
        include_evidence=bool(params.get("include_evidence", False)),
        max_nodes=int(params.get("max_nodes", params.get("limit", 100)) or 100),
        offset=int(params.get("offset", 0) or 0),
    )
    total = len(result)
    offset = int(params.get("offset", 0) or 0)
    # Direction-precise totals from per-node reach labels ("self" excluded).
    # Legacy "callers_total" previously echoed "total" for every direction,
    # misreporting callees as callers; "total" still carries the full count.
    reaches = [n.get("reach") if isinstance(n, dict) else None for n in result]
    if any(r is not None for r in reaches):
        callers = sum(1 for r in reaches if r in ("caller", "both"))
        callees = sum(1 for r in reaches if r in ("callee", "both"))
    else:
        # Foreign/legacy engine without reach labels: fall back to
        # direction-implied counts rather than failing.
        callers = total if p.direction in ("incoming", "both") else 0
        callees = total if p.direction in ("outgoing", "both") else 0
    response: dict[str, Any] = {
        "function": p.start,
        "direction": p.direction,
        "callers_total": callers,
        "callers_total_relation": "eq",
        "callees_total": callees,
        "nodes": result,
        "total": total,
        "offset": offset,
    }
    if p.direction == "both":
        response["note"] = (
            "direction=both unions true callers (reach=caller) and true callees "
            "(reach=callee) from separate traversals; nodes reachable only via "
            "a mixed out-then-in walk (e.g. sibling handlers sharing a helper) "
            "are excluded as neither."
        )
    return response


async def context(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/context``."""
    normalized = dict(params)
    if not normalized.get("file_path"):
        for alias in ("node_id", "entity", "id", "path"):
            if normalized.get(alias):
                normalized["file_path"] = normalized[alias]
                break
    p = msgspec.convert(normalized, ContextParams)
    engine = ctx["engine"]
    return await engine.get_context(p.file_path, p.scope, p.depth)  # type: ignore[no-any-return]


async def impact(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/impact``."""
    p = msgspec.convert(params, ImpactParams)
    engine = ctx["engine"]
    return await engine.assess_impact(p.entity, p.change_type)  # type: ignore[no-any-return]


async def locate(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/locate``."""
    p = msgspec.convert(params, LocateParams)
    engine = ctx["engine"]
    offset = int(params.get("offset", params.get("result_offset", 0)) or 0)
    match = str(params.get("match", "any"))
    if params.get("paged") or params.get("has_more") is not None or "offset" in params:
        return await engine.locate_paged(p.query, p.fields, p.node_types, p.top_k, offset, match)  # type: ignore[no-any-return]
    result = await engine.locate(p.query, p.fields, p.node_types, p.top_k, offset, match)
    return {"matches": result, "total": len(result), "offset": offset}


async def search(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/search``."""
    p = msgspec.convert(params, SearchParams)
    engine = ctx["engine"]
    offset = int(params.get("offset", params.get("result_offset", 0)) or 0)
    return await engine.search(p.query, p.match, p.filter, p.top_k, offset)  # type: ignore[no-any-return]


async def search_code(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/search_code`` — compact / full / files modes."""
    engine = ctx["engine"]
    return await engine.search_code(  # type: ignore[no-any-return]
        str(params.get("query", params.get("pattern", ""))),
        str(params.get("mode", "compact")),
        int(params.get("top_k", params.get("limit", 10)) or 10),
        int(params.get("offset", params.get("result_offset", 0)) or 0),
        str(params.get("match", "any")),
        params.get("node_types"),
    )


async def file_outline(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/file_outline``."""
    engine = ctx["engine"]
    file_path = str(params.get("file_path", params.get("path", params.get("file", ""))))
    return await engine.file_outline(  # type: ignore[no-any-return]
        file_path,
        int(params.get("limit", 200) or 200),
        int(params.get("offset", 0) or 0),
    )


async def coverage(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/coverage`` — index coverage signal."""
    engine = ctx["engine"]
    return await engine.index_coverage(str(params.get("scope", "full")))  # type: ignore[no-any-return]


async def dead_code(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/dead_code`` — zero-degree symbols."""
    engine = ctx["engine"]
    return await engine.dead_code(  # type: ignore[no-any-return]
        int(params.get("top_k", 50) or 50),
        bool(params.get("exclude_entry_points", True)),
    )


async def semantic_search(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/semantic_search``."""
    p = msgspec.convert(params, SemanticSearchParams)
    engine = ctx["engine"]
    return await engine.semantic_search(p.query, p.top_k, p.where, p.instruction)  # type: ignore[no-any-return]


async def flow(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/flow``."""
    p = msgspec.convert(params, FlowParams)
    engine = ctx["engine"]
    return await engine.find_flow(p.start, p.end, p.flow_type)  # type: ignore[no-any-return]


async def query(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/query`` — read-only graph query (query_graph parity)."""
    p = msgspec.convert(params, QueryParams)
    engine = ctx["engine"]
    return await engine.query_graph(  # type: ignore[no-any-return]
        p.query or str(params.get("cypher", params.get("q", ""))),
        int(params.get("max_rows", p.max_rows) or 200),
        int(params.get("offset", p.offset) or 0),
    )


async def code_snippet(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/code_snippet`` — get_code_snippet parity."""
    p = msgspec.convert(params, CodeSnippetParams)
    engine = ctx["engine"]
    qn = p.qualified_name or str(params.get("qn", params.get("function_name", params.get("name", ""))))
    return await engine.get_code_snippet(  # type: ignore[no-any-return]
        qn,
        str(params.get("source_mode", p.source_mode) or "auto"),
        int(params.get("max_lines", p.max_lines) or 500),
    )


async def detect_changes(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/detect_changes`` — git-aware detect_changes parity."""
    p = msgspec.convert(params, DetectChangesParams)
    engine = ctx["engine"]
    return await engine.detect_changes(  # type: ignore[no-any-return]
        str(params.get("base_branch", p.base_branch) or "main"),
        int(params.get("depth", p.depth) or 1),
        str(params.get("direction", p.direction) or "both"),
        int(params.get("limit", p.limit) or 50),
        str(params.get("scope", p.scope) or "files"),
    )
