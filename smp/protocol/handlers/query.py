"""Query method handlers (smp/navigate, smp/trace, smp/context, ...).

Each handler is a plain ``async def`` accepting ``(params, ctx)`` and
returning a JSON-serialisable dict.  ``ctx`` is expected to provide an
``engine`` (a :class:`~smp.engine.query.DefaultQueryEngine`).
"""

from __future__ import annotations

from typing import Any

import msgspec

from smp.core.models import (
    ContextParams,
    FlowParams,
    ImpactParams,
    LocateParams,
    NavigateParams,
    SearchParams,
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
    result = await engine.trace(p.start, p.relationship, p.depth, p.direction)
    return {"nodes": result}


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
    result = await engine.locate(p.query, p.fields, p.node_types, p.top_k)
    return {"matches": result}


async def search(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/search``."""
    p = msgspec.convert(params, SearchParams)
    engine = ctx["engine"]
    return await engine.search(p.query, p.match, p.filter, p.top_k)  # type: ignore[no-any-return]


async def flow(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/flow``."""
    p = msgspec.convert(params, FlowParams)
    engine = ctx["engine"]
    return await engine.find_flow(p.start, p.end, p.flow_type)  # type: ignore[no-any-return]
