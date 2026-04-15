"""JSON-RPC 2.0 dispatcher using handler pattern.

Routes JSON-RPC method calls to registered handler instances.
"""

from __future__ import annotations

from typing import Any

import msgspec
from fastapi import Request
from fastapi.responses import Response

from smp.core.models import (
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
)
from smp.logging import get_logger
from smp.protocol.handlers.annotation import (
    AnnotateBulkHandler,
    AnnotateHandler,
    TagHandler,
)
from smp.protocol.handlers.base import MethodHandler
from smp.protocol.handlers.community import (
    CommunityBoundariesHandler,
    CommunityDetectHandler,
    CommunityGetHandler,
    CommunityListHandler,
)
from smp.protocol.handlers.enrichment import (
    EnrichBatchHandler,
    EnrichHandler,
    EnrichStaleHandler,
    EnrichStatusHandler,
)
from smp.protocol.handlers.handoff import (
    HandoffPRHandler,
    HandoffReviewHandler,
)
from smp.protocol.handlers.memory import (
    BatchUpdateHandler,
    ReindexHandler,
    UpdateHandler,
)
from smp.protocol.handlers.merkle import (
    IndexExportHandler,
    IndexImportHandler,
    MerkleTreeHandler,
    SyncHandler,
)
from smp.protocol.handlers.query import (
    ContextHandler,
    FlowHandler,
    ImpactHandler,
    LocateHandler,
    NavigateHandler,
    SearchHandler,
    TraceHandler,
)
from smp.protocol.handlers.query_ext import (
    ConflictHandler,
    DiffHandler,
    PlanHandler,
    WhyHandler,
)
from smp.protocol.handlers.safety import (
    AuditGetHandler,
    CheckpointHandler,
    DryRunHandler,
    GuardCheckHandler,
    IntegrityVerifyHandler,
    LockHandler,
    RollbackHandler,
    SessionCloseHandler,
    SessionOpenHandler,
    SessionRecoverHandler,
    UnlockHandler,
)
from smp.protocol.handlers.sandbox import (
    SandboxDestroyHandler,
    SandboxExecuteHandler,
    SandboxSpawnHandler,
)
from smp.protocol.handlers.telemetry import (
    TelemetryHandler,
    TelemetryHotHandler,
    TelemetryNodeHandler,
    TelemetryRecordHandler,
)

log = get_logger(__name__)


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


class RpcDispatcher:
    """Dispatches JSON-RPC requests to registered handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, MethodHandler] = {}

        for handler_cls in [
            UpdateHandler,
            BatchUpdateHandler,
            ReindexHandler,
            EnrichHandler,
            EnrichBatchHandler,
            EnrichStaleHandler,
            EnrichStatusHandler,
            AnnotateHandler,
            AnnotateBulkHandler,
            TagHandler,
            SessionOpenHandler,
            SessionCloseHandler,
            SessionRecoverHandler,
            GuardCheckHandler,
            DryRunHandler,
            CheckpointHandler,
            RollbackHandler,
            LockHandler,
            UnlockHandler,
            AuditGetHandler,
            IntegrityVerifyHandler,
            NavigateHandler,
            TraceHandler,
            ContextHandler,
            ImpactHandler,
            LocateHandler,
            SearchHandler,
            FlowHandler,
            DiffHandler,
            PlanHandler,
            ConflictHandler,
            WhyHandler,
            TelemetryHandler,
            TelemetryHotHandler,
            TelemetryNodeHandler,
            TelemetryRecordHandler,
            SandboxSpawnHandler,
            SandboxExecuteHandler,
            SandboxDestroyHandler,
            CommunityDetectHandler,
            CommunityListHandler,
            CommunityGetHandler,
            CommunityBoundariesHandler,
            SyncHandler,
            MerkleTreeHandler,
            IndexExportHandler,
            IndexImportHandler,
            HandoffReviewHandler,
            HandoffPRHandler,
        ]:
            handler = handler_cls()
            self._handlers[handler.method] = handler

    def register(self, handler: MethodHandler) -> None:
        """Register a handler for a method."""
        self._handlers[handler.method] = handler
        log.debug("handler_registered", method=handler.method)

    def get_handler(self, method: str) -> MethodHandler | None:
        """Get handler for a method."""
        return self._handlers.get(method)

    async def dispatch(
        self,
        request: Request,
        context: dict[str, Any],
    ) -> Response:
        """Dispatch a JSON-RPC request to the appropriate handler."""
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

        if req.jsonrpc != "2.0":
            return _error_response(req.id, -32600, "Invalid Request: jsonrpc must be '2.0'")

        if not req.method:
            return _error_response(req.id, -32600, "Invalid Request: method is required")

        method = req.method
        params = req.params or {}

        log.debug("rpc_request", method=method, id=req.id)

        handler = self._handlers.get(method)
        if not handler:
            return _error_response(req.id, -32601, f"Method not found: {method}")

        try:
            result = await handler.handle(params, context)
        except msgspec.ValidationError as exc:
            return _error_response(req.id, -32602, f"Invalid params: {exc}")
        except ValueError as exc:
            return _error_response(req.id, -32001, str(exc))
        except Exception as exc:
            log.error("rpc_internal_error", method=method, error=str(exc))
            return _error_response(req.id, -32603, f"Internal error: {exc}")

        if req.id is None:
            return Response(content=b"", status_code=204)

        return _success_response(req.id, result)


_dispatcher: RpcDispatcher | None = None


def get_dispatcher() -> RpcDispatcher:
    """Get or create the global dispatcher instance."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = RpcDispatcher()
    return _dispatcher


async def handle_rpc(
    request: Request,
    *,
    engine: Any,
    enricher: Any,
    builder: Any,
    registry: Any,
    vector: Any,
    safety: dict[str, Any] | None = None,
    telemetry_engine: Any = None,
    handoff_manager: Any = None,
    integrity_verifier: Any = None,
) -> Response:
    """Dispatch a single JSON-RPC 2.0 request."""
    dispatcher = get_dispatcher()
    context = {
        "engine": engine,
        "enricher": enricher,
        "builder": builder,
        "registry": registry,
        "vector": vector,
        "safety": safety,
        "telemetry_engine": telemetry_engine,
        "handoff_manager": handoff_manager,
        "integrity_verifier": integrity_verifier,
    }
    return await dispatcher.dispatch(request, context)
