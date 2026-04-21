"""Handler for memory management methods (smp/update, smp/batch_update, etc.)."""

from __future__ import annotations

from typing import Any

import msgspec

from smp.core.models import BatchUpdateParams, Language, ReindexParams, UpdateParams
from smp.logging import get_logger
from smp.protocol.handlers.base import MethodHandler

log = get_logger(__name__)


class UpdateHandler(MethodHandler):
    """Handles smp/update method."""

    @property
    def method(self) -> str:
        return "smp/update"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        p = msgspec.convert(params, UpdateParams)
        enricher = context["enricher"]
        builder = context["builder"]
        registry = context["registry"]
        vector = context.get("vector")

        file_path = p.file_path

        # Auto-detect language from file extension if not provided
        language = p.language
        if not language:
            from smp.parser.base import detect_language
            language = detect_language(file_path)
            if language == Language.UNKNOWN:
                language = Language.PYTHON

        if p.content:
            parser_obj = registry.get(language)
            if not parser_obj:
                parser_obj = registry.get(Language.PYTHON)
                if not parser_obj:
                    return {"error": "No parser available"}
            doc = parser_obj.parse(p.content, file_path)
        else:
            doc = registry.parse_file(file_path)

        if not doc.nodes and not doc.edges:
            return {
                "file_path": file_path,
                "nodes": 0,
                "edges": 0,
                "errors": len(doc.errors),
                "message": "No nodes extracted",
            }

        enriched_nodes = await enricher.enrich_batch(doc.nodes)
        doc = type(doc)(
            file_path=doc.file_path,
            language=doc.language,
            nodes=enriched_nodes,
            edges=doc.edges,
            errors=doc.errors,
        )

        if vector:
            await vector.delete_by_file(file_path)
            await builder.remove_document(file_path)
            await builder.ingest_document(doc)

        await builder.resolve_pending_edges()

        return {
            "file_path": file_path,
            "nodes": len(doc.nodes),
            "edges": len(doc.edges),
            "errors": len(doc.errors),
        }


class BatchUpdateHandler(MethodHandler):
    """Handles smp/batch_update method."""

    @property
    def method(self) -> str:
        return "smp/batch_update"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        bp = msgspec.convert(params, BatchUpdateParams)
        update_handler = UpdateHandler()

        results = []
        for change in bp.changes:
            r = await update_handler.handle(change, context)
            results.append(r)

        return {"updates": len(results), "results": results}


class ReindexHandler(MethodHandler):
    """Handles smp/reindex method."""

    @property
    def method(self) -> str:
        return "smp/reindex"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        rp = msgspec.convert(params, ReindexParams)
        return {"status": "reindex_requested", "scope": rp.scope}
