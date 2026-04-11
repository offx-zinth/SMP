"""Handler for query methods (smp/navigate, smp/trace, smp/context, etc.)."""

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
from smp.protocol.handlers.base import MethodHandler

log = get_logger(__name__)


class NavigateHandler(MethodHandler):
    """Handles smp/navigate method."""

    @property
    def method(self) -> str:
        return "smp/navigate"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        np_ = msgspec.convert(params, NavigateParams)
        engine = context["engine"]
        return await engine.navigate(np_.query, np_.include_relationships)


class TraceHandler(MethodHandler):
    """Handles smp/trace method."""

    @property
    def method(self) -> str:
        return "smp/trace"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        trp = msgspec.convert(params, TraceParams)
        engine = context["engine"]
        result = await engine.trace(trp.start, trp.relationship, trp.depth, trp.direction)
        return {"nodes": result}


class ContextHandler(MethodHandler):
    """Handles smp/context method."""

    @property
    def method(self) -> str:
        return "smp/context"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        ctp = msgspec.convert(params, ContextParams)
        engine = context["engine"]
        return await engine.get_context(ctp.file_path, ctp.scope, ctp.depth)


class ImpactHandler(MethodHandler):
    """Handles smp/impact method."""

    @property
    def method(self) -> str:
        return "smp/impact"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        imp = msgspec.convert(params, ImpactParams)
        engine = context["engine"]
        return await engine.assess_impact(imp.entity, imp.change_type)


class LocateHandler(MethodHandler):
    """Handles smp/locate method."""

    @property
    def method(self) -> str:
        return "smp/locate"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        loc = msgspec.convert(params, LocateParams)
        engine = context["engine"]
        result = await engine.locate(loc.query, loc.fields, loc.node_types, loc.top_k)
        return {"matches": result}


class SearchHandler(MethodHandler):
    """Handles smp/search method."""

    @property
    def method(self) -> str:
        return "smp/search"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        sp = msgspec.convert(params, SearchParams)
        engine = context["engine"]
        return await engine.search(sp.query, sp.match, sp.filter, sp.top_k)


class FlowHandler(MethodHandler):
    """Handles smp/flow method."""

    @property
    def method(self) -> str:
        return "smp/flow"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        fp = msgspec.convert(params, FlowParams)
        engine = context["engine"]
        return await engine.find_flow(fp.start, fp.end, fp.flow_type)
