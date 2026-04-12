"""Handler for diff, plan, conflict, why, and telemetry methods."""

from __future__ import annotations

from typing import Any

import msgspec

from smp.core.models import (
    ConflictParams,
    DiffParams,
    PlanParams,
    TelemetryParams,
    WhyParams,
)
from smp.logging import get_logger
from smp.protocol.handlers.base import MethodHandler

log = get_logger(__name__)


class DiffHandler(MethodHandler):
    """Handles smp/diff method."""

    @property
    def method(self) -> str:
        return "smp/diff"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        dp = msgspec.convert(params, DiffParams)
        engine = context["engine"]
        return await engine.diff(dp.from_snapshot, dp.to_snapshot, dp.scope)


class PlanHandler(MethodHandler):
    """Handles smp/plan method."""

    @property
    def method(self) -> str:
        return "smp/plan"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        pp = msgspec.convert(params, PlanParams)
        engine = context["engine"]
        return await engine.plan(pp.change_description, pp.target_file, pp.change_type, pp.scope)


class ConflictHandler(MethodHandler):
    """Handles smp/conflict method."""

    @property
    def method(self) -> str:
        return "smp/conflict"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        cp = msgspec.convert(params, ConflictParams)
        engine = context["engine"]
        return await engine.conflict(cp.entity, cp.proposed_change, cp.context)


class WhyHandler(MethodHandler):
    """Handles smp/why method."""

    @property
    def method(self) -> str:
        return "smp/graph/why"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        wp = msgspec.convert(params, WhyParams)
        engine = context["engine"]
        return await engine.why(wp.entity, wp.relationship, wp.depth)


class TelemetryHandler(MethodHandler):
    """Handles smp/telemetry method."""

    @property
    def method(self) -> str:
        return "smp/telemetry"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        tp = msgspec.convert(params, TelemetryParams)
        telemetry_engine = context.get("telemetry_engine")
        if not telemetry_engine:
            # Return basic stats if telemetry not configured
            return {"action": tp.action, "status": "not_configured"}

        if tp.action == "get_stats":
            return telemetry_engine.get_summary()
        elif tp.action == "get_hot" and tp.node_id:
            return telemetry_engine.get_stats(tp.node_id)
        elif tp.action == "decay":
            return {"decayed": telemetry_engine.decay()}
        else:
            return {"error": "Unknown telemetry action"}
