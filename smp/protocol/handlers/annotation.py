"""Handler for annotation methods (smp/annotate, smp/annotate/bulk, smp/tag)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import msgspec

from smp.core.models import AnnotateBulkParams, AnnotateParams, TagParams
from smp.logging import get_logger
from smp.protocol.handlers.base import MethodHandler

log = get_logger(__name__)


class AnnotateHandler(MethodHandler):
    """Handles smp/annotate method."""

    @property
    def method(self) -> str:
        return "smp/annotate"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        ap = msgspec.convert(params, AnnotateParams)
        engine = context["engine"]

        node = await engine._graph.get_node(ap.node_id)
        if not node:
            raise ValueError(f"Node not found: {ap.node_id}")

        if node.semantic.docstring and not ap.force:
            raise ValueError(f"Node already has extracted docstring. Set force: true to override. Node: {ap.node_id}")

        node.semantic.description = ap.description
        node.semantic.tags = list(set(node.semantic.tags + ap.tags))
        node.semantic.manually_set = True
        node.semantic.status = "manually_annotated"
        node.semantic.enriched_at = datetime.now(UTC).isoformat()
        await engine._graph.upsert_node(node)

        return {
            "node_id": ap.node_id,
            "status": "annotated",
            "manually_set": True,
            "annotated_at": node.semantic.enriched_at,
        }


class AnnotateBulkHandler(MethodHandler):
    """Handles smp/annotate/bulk method."""

    @property
    def method(self) -> str:
        return "smp/annotate/bulk"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        abp = msgspec.convert(params, AnnotateBulkParams)
        engine = context["engine"]

        annotated = 0
        failed = 0

        for ann in abp.annotations:
            node = await engine._graph.get_node(ann.node_id)
            if not node:
                failed += 1
                continue

            node.semantic.description = ann.description
            node.semantic.tags = list(set(node.semantic.tags + ann.tags))
            node.semantic.manually_set = True
            node.semantic.status = "manually_annotated"
            node.semantic.enriched_at = datetime.now(UTC).isoformat()
            await engine._graph.upsert_node(node)
            annotated += 1

        return {"annotated": annotated, "failed": failed}


class TagHandler(MethodHandler):
    """Handles smp/tag method."""

    @property
    def method(self) -> str:
        return "smp/tag"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        tp = msgspec.convert(params, TagParams)
        engine = context["engine"]

        nodes = await engine._graph.find_nodes_by_scope(tp.scope)
        affected = 0

        for node in nodes:
            if tp.action == "add":
                node.semantic.tags = list(set(node.semantic.tags + tp.tags))
            elif tp.action == "remove":
                node.semantic.tags = [t for t in node.semantic.tags if t not in tp.tags]
            elif tp.action == "replace":
                node.semantic.tags = list(tp.tags)
            await engine._graph.upsert_node(node)
            affected += 1

        return {"nodes_affected": affected, "action": tp.action, "scope": tp.scope}
