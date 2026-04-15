"""Telemetry handlers for SMP(3)."""

from __future__ import annotations

from typing import Any

import msgspec

from smp.core.models import (
    TelemetryParams,
)
from smp.logging import get_logger
from smp.protocol.handlers.base import MethodHandler

log = get_logger(__name__)


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
            return {"action": tp.action, "status": "not_configured"}
        elif tp.action == "get_stats":
            return telemetry_engine.get_summary()
        elif tp.action == "get_hot" and tp.node_id:
            return telemetry_engine.get_stats(tp.node_id)
        elif tp.action == "decay":
            return {"decayed": telemetry_engine.decay()}
        else:
            return {"error": "Unknown telemetry action"}


class TelemetryHotHandler(MethodHandler):
    """Handles smp/telemetry/hot method."""

    @property
    def method(self) -> str:
        return "smp/telemetry/hot"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        # Extract node_id from params
        node_id = params.get("node_id")
        if not node_id:
            return {"error": "node_id is required"}

        telemetry_engine = context.get("telemetry_engine")
        if not telemetry_engine:
            return {"status": "not_configured"}

        return telemetry_engine.get_stats(node_id)


class TelemetryNodeHandler(MethodHandler):
    """Handles smp/telemetry/node method."""

    @property
    def method(self) -> str:
        return "smp/telemetry/node"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        # Extract node_id from params
        node_id = params.get("node_id")
        if not node_id:
            return {"error": "node_id is required"}

        telemetry_engine = context.get("telemetry_engine")
        if not telemetry_engine:
            return {"status": "not_configured"}

        return telemetry_engine.get_stats(node_id)


class TelemetryRecordHandler(MethodHandler):
    """Handles smp/telemetry/record method."""

    @property
    def method(self) -> str:
        return "smp/telemetry/record"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        # Extract parameters
        node_id = params.get("node_id")
        action = params.get("action", "access")
        session_id = params.get("session_id")
        agent_id = params.get("agent_id")

        if not node_id:
            return {"error": "node_id is required"}

        telemetry_engine = context.get("telemetry_engine")
        if not telemetry_engine:
            return {"status": "not_configured"}

        return telemetry_engine.record_access(
            node_id=node_id,
            action=action,
            session_id=session_id or "",
            agent_id=agent_id or "",
        )
