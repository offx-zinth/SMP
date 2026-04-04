"""JSON-RPC 2.0 dispatcher for the Structural Memory Protocol.

All SMP protocol methods are routed through a single ``POST /rpc`` endpoint.
Request/response encoding uses ``msgspec`` for zero-cost serialization.
"""

from __future__ import annotations

from typing import Any

import msgspec
from fastapi import Request
from fastapi.responses import Response

from smp.core.models import (
    ContextParams,
    FlowParams,
    ImpactParams,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    Language,
    LocateParams,
    NavigateParams,
    TraceParams,
    UpdateParams,
)
from smp.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# JSON-RPC error codes
# _PARSE_ERROR = -32700
# _INVALID_REQUEST = -32600
# _METHOD_NOT_FOUND = -32601
# _INVALID_PARAMS = -32602
# _INTERNAL_ERROR = -32603


def _error_response(req_id: int | str | None, code: int, message: str, data: Any = None) -> Response:
    body = msgspec.json.encode(
        JsonRpcResponse(
            error=JsonRpcError(code=code, message=message, data=data),
            id=req_id,
        )
    )
    return Response(content=body, media_type="application/json", status_code=200)


def _success_response(req_id: int | str | None, result: Any) -> Response:
    body = msgspec.json.encode(JsonRpcResponse(result=result, id=req_id))
    return Response(content=body, media_type="application/json", status_code=200)


# ---------------------------------------------------------------------------
# Update handler (special: uses parser + builder + enricher + vector store)
# ---------------------------------------------------------------------------

async def _handle_update(
    params: dict[str, Any],
    engine: Any,
    enricher: Any,
    builder: Any,
    registry: Any,
    vector: Any,
) -> dict[str, Any]:
    p = msgspec.convert(params, UpdateParams)
    from pathlib import Path

    file_path = p.file_path

    # Parse: either from provided content or read from disk
    if p.content:
        parser_obj = registry.get(p.language)
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

    # Enrich
    enriched_nodes = await enricher.enrich_batch(doc.nodes)
    doc = type(doc)(
        file_path=doc.file_path,
        language=doc.language,
        nodes=enriched_nodes,
        edges=doc.edges,
        errors=doc.errors,
    )

    # Remove old data (graph + vectors) and ingest new
    await vector.delete_by_file(file_path)
    await builder.remove_document(file_path)
    await builder.ingest_document(doc)

    # Upsert embeddings to vector store
    embed_ids: list[str] = []
    embed_vecs: list[list[float]] = []
    embed_metas: list[dict[str, Any]] = []
    embed_docs: list[str] = []
    for n in enriched_nodes:
        if n.semantic and n.semantic.embedding:
            embed_ids.append(n.id)
            embed_vecs.append(n.semantic.embedding)
            embed_metas.append({"name": n.name, "file_path": n.file_path, "type": n.type.value})
            embed_docs.append(n.semantic.purpose)

    if embed_ids:
        await vector.upsert(ids=embed_ids, embeddings=embed_vecs, metadatas=embed_metas, documents=embed_docs)

    return {
        "file_path": file_path,
        "nodes": len(doc.nodes),
        "edges": len(doc.edges),
        "errors": len(doc.errors),
        "enriched": len(embed_ids),
    }


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------

async def handle_rpc(
    request: Request,
    *,
    engine: Any,
    enricher: Any,
    builder: Any,
    registry: Any,
    vector: Any,
) -> Response:
    """Dispatch a single JSON-RPC 2.0 request.

    Designed to be called from a FastAPI route handler.
    """
    # 1. Read and parse body
    try:
        body = await request.body()
    except Exception:
        return _error_response(None, -32700, "Parse error")

    if not body:
        return _error_response(None, -32700, "Empty request body")

    try:
        req = msgspec.json.decode(body, type=JsonRpcRequest)
    except (msgspec.DecodeError, Exception) as exc:
        return _error_response(None, -32700, f"Parse error: {exc}")

    # 2. Validate JSON-RPC version
    if req.jsonrpc != "2.0":
        return _error_response(req.id, -32600, "Invalid Request: jsonrpc must be '2.0'")

    if not req.method:
        return _error_response(req.id, -32600, "Invalid Request: method is required")

    # 3. Route to handler
    method = req.method
    params = req.params

    log.debug("rpc_request", method=method, id=req.id)

    try:
        if method == "smp/navigate":
            p = msgspec.convert(params, NavigateParams)
            result = await engine.navigate(p.entity_id, p.depth)

        elif method == "smp/trace":
            p = msgspec.convert(params, TraceParams)
            result = await engine.trace(p.start_id, p.edge_type.value, p.depth, p.max_nodes)

        elif method == "smp/context":
            p = msgspec.convert(params, ContextParams)
            result = await engine.get_context(p.file_path, p.scope, p.include_semantic)

        elif method == "smp/impact":
            p = msgspec.convert(params, ImpactParams)
            result = await engine.assess_impact(p.entity_id, p.depth)

        elif method == "smp/locate":
            p = msgspec.convert(params, LocateParams)
            result = await engine.locate_by_intent(p.description, p.top_k)

        elif method == "smp/flow":
            p = msgspec.convert(params, FlowParams)
            result = await engine.find_flow(p.start_id, p.end_id, p.max_depth)

        elif method == "smp/update":
            result = await _handle_update(params, engine, enricher, builder, registry, vector)

        else:
            return _error_response(req.id, -32601, f"Method not found: {method}")

    except msgspec.ValidationError as exc:
        return _error_response(req.id, -32602, f"Invalid params: {exc}")
    except Exception as exc:
        log.error("rpc_internal_error", method=method, error=str(exc))
        return _error_response(req.id, -32603, f"Internal error: {exc}")

    # Notifications (no id) don't get a response
    if req.id is None:
        return Response(content=b"", status_code=204)

    return _success_response(req.id, result)
