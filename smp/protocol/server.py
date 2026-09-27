"""FastAPI application with JSON-RPC 2.0 endpoint.

Start with: ``python3.11 -m smp.cli serve``

The server keeps a small surface area: an ``MMapGraphStore`` plus the
high-level :class:`DefaultQueryEngine` and the handler modules under
:mod:`smp.protocol.handlers`.  All RPC dispatching is done inline here
through a method->handler table.
"""

from __future__ import annotations

import asyncio
import signal
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from smp.core.config import Settings
from smp.embedding.service import EMBEDDING_DIM, QwenEmbeddingService, get_embedding_service
from smp.engine.graph_builder import DefaultGraphBuilder
from smp.engine.query import DefaultQueryEngine
from smp.logging import get_logger
from smp.observability.backup import backup as backup_store
from smp.observability.backup import compact as compact_store
from smp.observability.metrics import MetricsRegistry, install_standard_metrics
from smp.protocol.auth import (
    AuthPolicy,
    RateLimiter,
    Scope,
    extract_token,
    required_scope,
    rpc_error,
    safe_internal_error,
)
from smp.protocol.handlers import (
    analysis as analysis_handlers,
)
from smp.protocol.handlers import (
    community as community_handlers,
)
from smp.protocol.handlers import (
    enrichment as enrichment_handlers,
)
from smp.protocol.handlers import (
    memory as memory_handlers,
)
from smp.protocol.handlers import (
    query as query_handlers,
)
from smp.protocol.handlers import (
    review as review_handlers,
)
from smp.protocol.handlers import (
    sandbox as sandbox_handlers,
)
from smp.protocol.handlers import (
    session as session_handlers,
)
from smp.protocol.handlers import (
    sync as sync_handlers,
)
from smp.protocol.handlers import (
    vector as vector_handlers,
)
from smp.runtime.sandbox import SandboxRuntime
from smp.store.graph.mmap_store import MMapGraphStore
from smp.vector.mmap_vector import MMapVectorStore

log = get_logger(__name__)


HandlerFn = Callable[[dict[str, Any], dict[str, Any]], Awaitable[Any]]


class _PayloadParseError(Exception):
    """Raised when JSON payload parsing fails."""


def msgspec_json_decode(body: bytes) -> Any:
    """Decode a JSON-RPC payload, raising :class:`_PayloadParseError` on failure."""
    import json

    if not body:
        raise _PayloadParseError("empty body")
    try:
        return json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _PayloadParseError(str(exc)) from exc


_HANDLERS: dict[str, HandlerFn] = {
    # Query
    "smp/navigate": query_handlers.navigate,
    "smp/trace": query_handlers.trace,
    "smp/context": query_handlers.context,
    "smp/impact": query_handlers.impact,
    "smp/locate": query_handlers.locate,
    "smp/search": query_handlers.search,
    "smp/semantic_search": query_handlers.semantic_search,
    "smp/flow": query_handlers.flow,
    # Memory management
    "smp/update": memory_handlers.update,
    "smp/batch_update": memory_handlers.batch_update,
    "smp/reindex": memory_handlers.reindex,
    # Analysis & telemetry
    "smp/diff": analysis_handlers.diff,
    "smp/plan": analysis_handlers.plan,
    "smp/conflict": analysis_handlers.conflict,
    "smp/why": analysis_handlers.why,
    "smp/telemetry": analysis_handlers.telemetry,
    "smp/telemetry/hot": analysis_handlers.telemetry_hot,
    "smp/telemetry/node": analysis_handlers.telemetry_node,
    # Enrichment & annotation
    "smp/enrich": enrichment_handlers.enrich,
    "smp/enrich/batch": enrichment_handlers.enrich_batch,
    "smp/enrich/stale": enrichment_handlers.enrich_stale,
    "smp/enrich/status": enrichment_handlers.enrich_status,
    "smp/annotate": enrichment_handlers.annotate,
    "smp/annotate/bulk": enrichment_handlers.annotate_bulk,
    "smp/tag": enrichment_handlers.tag,
    # Session, safety, audit
    "smp/session/open": session_handlers.session_open,
    "smp/session/close": session_handlers.session_close,
    "smp/session/recover": session_handlers.session_recover,
    "smp/dryrun": session_handlers.dryrun,
    "smp/checkpoint": session_handlers.checkpoint,
    "smp/rollback": session_handlers.rollback,
    "smp/lock": session_handlers.lock,
    "smp/unlock": session_handlers.unlock,
    "smp/audit/get": session_handlers.audit_get,
    # Review & PR handoff
    "smp/review/create": review_handlers.review_create,
    "smp/review/approve": review_handlers.review_approve,
    "smp/review/reject": review_handlers.review_reject,
    "smp/review/comment": review_handlers.review_comment,
    "smp/pr/create": review_handlers.pr_create,
    # Sandbox lifecycle
    "smp/sandbox/spawn": sandbox_handlers.sandbox_spawn,
    "smp/sandbox/execute": sandbox_handlers.sandbox_execute,
    "smp/sandbox/kill": sandbox_handlers.sandbox_kill,
    # Community detection
    "smp/community/detect": community_handlers.community_detect,
    "smp/community/list": community_handlers.community_list,
    "smp/community/get": community_handlers.community_get,
    "smp/community/boundaries": community_handlers.community_boundaries,
    # Sync, import, integrity
    "smp/sync": sync_handlers.sync,
    "smp/index/import": sync_handlers.index_import,
    "smp/integrity/check": sync_handlers.integrity_check,
    "smp/integrity/baseline": sync_handlers.integrity_baseline,
    "smp/vector/search": vector_handlers.vector_search,
    "smp/vector/upsert": vector_handlers.vector_upsert,
    "smp/vector/delete": vector_handlers.vector_delete,
    "smp/vector/semantic_search": vector_handlers.vector_semantic_search,
}


class _MethodNotFoundError(Exception):
    """Raised when an RPC method is not registered."""

    def __init__(self, method: str) -> None:
        super().__init__(method)
        self.method = method


async def _dispatch(method: str, params: dict[str, Any], ctx: dict[str, Any]) -> Any:
    """Resolve and invoke the handler for ``method``."""
    handler = _HANDLERS.get(method)
    if handler is None:
        raise _MethodNotFoundError(method)
    return await handler(params, ctx)


def setup_graceful_shutdown(server: Any, app: FastAPI) -> None:
    """Setup SIGTERM handler for graceful shutdown.

    On SIGTERM:
    1. Stops accepting new requests
    2. Waits for in-flight requests to complete (30s timeout)
    3. Flushes all buffers (journal fsync)
    4. Closes connections cleanly

    Parameters
    ----------
    server
        The uvicorn.Server instance to signal shutdown
    app
        The FastAPI application instance
    """

    _shutdown_event = asyncio.Event()

    def _in_flight_count() -> int:
        return int(getattr(app, "state", None) and getattr(app.state, "active_request_count", 0) or 0)

    async def shutdown_handler(signum: int, frame: Any) -> None:
        """SIGTERM signal handler for graceful shutdown."""
        log.info("sigterm_received", signal=signum)

        # Phase 1: Stop accepting new requests
        log.info("shutdown_phase_1_stop_accepting_requests")
        server.should_exit = True

        # Phase 2: Wait for in-flight requests (max 30s)
        log.info("shutdown_phase_2_wait_in_flight_requests")
        timeout = 30.0
        start = time.time()
        while _in_flight_count() > 0 and (time.time() - start) < timeout:
            await asyncio.sleep(0.5)
            if _in_flight_count() > 0:
                log.info(
                    "waiting_for_requests",
                    in_flight=_in_flight_count(),
                    elapsed_s=round(time.time() - start, 1),
                )

        if _in_flight_count() > 0:
            log.warning(
                "shutdown_timeout_requests_still_in_flight",
                count=_in_flight_count(),
            )

        # Phase 3: Flush all buffers
        log.info("shutdown_phase_3_flush_buffers")
        try:
            graph: MMapGraphStore | None = getattr(app.state, "graph", None)
            if graph is not None:
                await graph.flush()
                log.info("shutdown_graph_store_flushed")
        except Exception as exc:  # noqa: BLE001
            log.exception("shutdown_graph_store_flush_failed", error=str(exc))

        # Phase 4: Close connections
        log.info("shutdown_phase_4_close_connections")
        try:
            graph_store: MMapGraphStore | None = getattr(app.state, "graph", None)
            vector_store: MMapVectorStore | None = getattr(app.state, "vector_store", None)
            embedding_service: QwenEmbeddingService | None = getattr(app.state, "embedding_service", None)

            if graph_store is not None:
                await graph_store.close()
                log.info("shutdown_graph_store_closed")

            if vector_store is not None:
                await vector_store.close()
                log.info("shutdown_vector_store_closed")

            if embedding_service is not None:
                await embedding_service.close()
                log.info("shutdown_embedding_service_closed")
        except Exception as exc:  # noqa: BLE001
            log.exception("shutdown_store_close_failed", error=str(exc))

        log.info("shutdown_complete")
        _shutdown_event.set()

    def signal_handler(signum: int, frame: Any) -> None:
        """Wrapper to schedule async shutdown handler."""
        with suppress(RuntimeError):
            # RuntimeError raised if no event loop is running yet
            asyncio.create_task(shutdown_handler(signum, frame))

    # Install SIGTERM handler
    try:
        signal.signal(signal.SIGTERM, signal_handler)
        log.info("graceful_shutdown_handler_installed")
    except Exception as exc:  # noqa: BLE001
        log.warning("graceful_shutdown_handler_install_failed", error=str(exc))


def create_app(
    graph_path: str | None = None,
    vector_path: str | None = None,
    safety_enabled: bool = False,  # accepted for backward CLI compat; unused
    auth_policy: AuthPolicy | None = None,
) -> FastAPI:
    """Create and configure the SMP FastAPI application.

    Parameters
    ----------
    graph_path
        Override location of the ``.smpg`` file (defaults to ``Settings``).
    vector_path
        Override location of the ``.smpv`` file (defaults to ``Settings``).
    auth_policy
        Optional pre-built :class:`AuthPolicy`.  If omitted the policy is
        loaded from environment variables on each call (so tests can pin
        a deterministic policy without polluting the global env).
    """
    del safety_enabled
    settings = Settings.from_env()
    resolved_graph_path = graph_path or settings.graph_path
    resolved_vector_path = vector_path or settings.vector_path

    policy = auth_policy or AuthPolicy.from_env()
    limiter = RateLimiter(policy.rate_limit_per_minute)
    metrics = MetricsRegistry()
    install_standard_metrics(metrics)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]  # noqa: ANN202
        Path(resolved_graph_path).parent.mkdir(parents=True, exist_ok=True)
        Path(resolved_vector_path).parent.mkdir(parents=True, exist_ok=True)
        graph = MMapGraphStore(path=resolved_graph_path)
        await graph.connect()

        vector_store = MMapVectorStore(path=resolved_vector_path, dimension=EMBEDDING_DIM)
        await vector_store.connect()

        embedding_service = await get_embedding_service()
        vector_store.set_embedding_service(embedding_service)

        engine = DefaultQueryEngine(graph_store=graph, vector_store=vector_store)
        builder = DefaultGraphBuilder(graph)

        app.state.graph = graph
        app.state.vector_store = vector_store
        app.state.embedding_service = embedding_service
        app.state.engine = engine
        app.state.builder = builder
        app.state.auth_policy = policy
        app.state.rate_limiter = limiter
        app.state.metrics = metrics
        app.state.runtime_ctx = {
            "engine": engine,
            "builder": builder,
            "graph": graph,
            "vector_store": vector_store,
            "embedding_service": embedding_service,
            "metrics": metrics,
            # Shared per-process runtime state. The ``/rpc`` endpoint
            # shallow-copies this dict per request, so anything handlers
            # stash via ``ctx.setdefault`` (reviews, sandboxes, community
            # cache, sessions, locks, audit log) must be pre-seeded here —
            # otherwise it is lost after each response.
            "_sessions": {},
            "_locks": {},
            "_audit_log": [],
            "_reviews": {},
            "_pull_requests": {},
            "_sandbox_runtime": SandboxRuntime(),
            "_communities": {"by_id": {}, "node_to_id": {}, "level": 0},
        }

        log.info(
            "server_started",
            graph_path=resolved_graph_path,
            auth_open_mode=policy.open_mode,
            rate_limit=policy.rate_limit_per_minute,
        )
        try:
            yield
        finally:
            await graph.close()
            await vector_store.close()
            embedding_service_obj = getattr(app.state, "embedding_service", None)
            if embedding_service_obj is not None:
                await embedding_service_obj.close()
            log.info("server_stopped")

    app = FastAPI(
        title="SMP — Structural Memory Protocol",
        version="3.0.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def correlation_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        request.state.correlation_id = correlation_id
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        app.state.active_request_count = getattr(app.state, "active_request_count", 0) + 1
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        finally:
            app.state.active_request_count = max(0, getattr(app.state, "active_request_count", 1) - 1)
            structlog.contextvars.clear_contextvars()

    async def _authenticate(request: Request) -> Any:
        """Return a :class:`Principal` or a JSON ``401`` response."""
        token = extract_token(request.headers)
        principal = policy.authenticate(token)
        if principal is None:
            return JSONResponse(rpc_error(-32001, "Unauthorized"), status_code=401)
        return principal

    @app.post("/rpc")
    async def rpc_endpoint(request: Request) -> Any:
        principal_or_resp = await _authenticate(request)
        if isinstance(principal_or_resp, JSONResponse):
            return principal_or_resp
        principal = principal_or_resp

        # Enforce request-size cap before reading the body
        max_bytes = policy.max_request_bytes
        cl_header = request.headers.get("content-length")
        if cl_header:
            try:
                if int(cl_header) > max_bytes:
                    return JSONResponse(rpc_error(-32600, "Request body too large"), status_code=413)
            except ValueError:
                pass

        body = await request.body()
        if len(body) > max_bytes:
            return JSONResponse(rpc_error(-32600, "Request body too large"), status_code=413)

        try:
            payload = msgspec_json_decode(body)
        except _PayloadParseError:
            return rpc_error(-32700, "Parse error")

        if not isinstance(payload, dict):
            return rpc_error(-32600, "Invalid request")

        request_id = payload.get("id")
        method = payload.get("method")
        params = payload.get("params") or {}
        if not isinstance(method, str) or not method:
            return rpc_error(-32600, "Invalid request", request_id)
        if not isinstance(params, dict):
            params = {}

        if not principal.has(required_scope(method)):
            return JSONResponse(rpc_error(-32002, "Forbidden", request_id), status_code=403)

        if not limiter.allow(principal):
            return JSONResponse(
                rpc_error(-32003, "Rate limit exceeded", request_id),
                status_code=429,
            )

        try:
            runtime_ctx = app.state.runtime_ctx
        except (AttributeError, KeyError):
            log.warning("rpc_server_not_ready", method=method)
            return JSONResponse(rpc_error(-32603, "Server not ready", request_id), status_code=503)

        ctx: dict[str, Any] = dict(runtime_ctx)
        ctx["principal"] = principal
        ctx["correlation_id"] = request.state.correlation_id

        start = time.perf_counter()
        status = "ok"
        try:
            result = await _dispatch(method, params, ctx)
        except _MethodNotFoundError as exc:
            metrics.inc("smp_rpc_requests_total", method=method, status="method_not_found")
            metrics.inc("smp_rpc_errors_total", method=method, code="-32601")
            log.info(
                "rpc_unknown_method",
                method=method,
                principal=principal.name,
            )
            return rpc_error(-32601, f"Method not found: {exc.method}", request_id)
        except Exception:  # noqa: BLE001
            metrics.inc("smp_rpc_requests_total", method=method, status="error")
            metrics.inc("smp_rpc_errors_total", method=method, code="-32603")
            log.exception("rpc_handler_failed", method=method, principal=principal.name)
            return safe_internal_error(request_id)
        finally:
            duration = time.perf_counter() - start
            metrics.observe("smp_rpc_duration_seconds", duration, method=method)

        metrics.inc("smp_rpc_requests_total", method=method, status=status)
        log.info(
            "rpc_handled",
            method=method,
            principal=principal.name,
            duration_ms=round(duration * 1000.0, 2),
        )
        return {"jsonrpc": "2.0", "result": result, "id": request_id}

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe — returns ``200`` whenever the process is up.

        Deliberately public and free of any state inspection so external
        load balancers can hit it without credentials.
        """
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> Any:
        """Readiness probe — verifies the graph store is open and queryable."""
        graph: MMapGraphStore = app.state.graph
        try:
            await graph.count_nodes()
        except Exception:  # noqa: BLE001
            log.exception("readiness_check_failed")
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return {"status": "ready"}

    @app.get("/health/detailed")
    async def health_detailed() -> Any:
        """Detailed health check with dependency status and latencies.

        Returns a comprehensive health report including:
        - Overall status (healthy, degraded, unhealthy)
        - Per-component status and latency
        - Journal metadata
        - Recommendations for remediation
        """
        import time

        graph: MMapGraphStore = app.state.graph
        vector_store: MMapVectorStore = app.state.vector_store
        checks: dict[str, dict[str, Any]] = {}
        overall_status = "healthy"

        # 1. Graph store accessibility
        try:
            start = time.perf_counter()
            count = await graph.count_nodes()
            latency_ms = (time.perf_counter() - start) * 1000
            checks["graph_store"] = {
                "status": "accessible",
                "latency_ms": round(latency_ms, 2),
                "nodes": count,
            }
        except Exception as exc:  # noqa: BLE001
            checks["graph_store"] = {
                "status": "inaccessible",
                "error": str(exc)[:100],
            }
            overall_status = "unhealthy"
            log.exception("health_check_graph_store_failed")

        # 2. Vector store accessibility
        try:
            start = time.perf_counter()
            count = len(vector_store)
            latency_ms = (time.perf_counter() - start) * 1000
            checks["vector_store"] = {
                "status": "accessible",
                "latency_ms": round(latency_ms, 2),
                "embeddings": count,
            }
        except Exception as exc:  # noqa: BLE001
            checks["vector_store"] = {
                "status": "degraded",
                "error": str(exc)[:100],
            }
            if overall_status == "healthy":
                overall_status = "degraded"
            log.exception("health_check_vector_store_failed")

        # 3. Journal health
        try:
            journal_checks = {
                "status": "healthy",
                "file_size_bytes": graph.file.size,
                "data_end_bytes": graph.file.data_region_end,
                "sessions_active": len(graph._sessions),  # noqa: SLF001
                "locks_active": len(graph._locks),  # noqa: SLF001
                "audit_entries": len(graph._audit),  # noqa: SLF001
            }
            checks["journal"] = journal_checks
        except Exception as exc:  # noqa: BLE001
            checks["journal"] = {
                "status": "degraded",
                "error": str(exc)[:100],
            }
            if overall_status == "healthy":
                overall_status = "degraded"
            log.exception("health_check_journal_failed")

        # 4. Redis accessibility (if configured) - optional, skipped if not configured
        try:
            from smp.core.config import Settings

            settings = Settings.from_env()
            redis_url = getattr(settings, "redis_url", None)
            if redis_url:
                # Redis is configured but optional, mark as degraded if unavailable
                checks["redis"] = {
                    "status": "not_tested",
                    "note": "Redis checks skipped (optional service)",
                }
        except Exception:  # noqa: BLE001
            # Silently skip Redis check if it can't be configured
            pass

        return {
            "status": overall_status,
            "timestamp": time.time(),
            "checks": checks,
        }

    @app.get("/stats")
    async def stats(request: Request) -> Any:
        principal_or_resp = await _authenticate(request)
        if isinstance(principal_or_resp, JSONResponse):
            return principal_or_resp
        if not principal_or_resp.has(Scope.READ):
            return JSONResponse(rpc_error(-32002, "Forbidden"), status_code=403)
        graph: MMapGraphStore = app.state.graph
        return {
            "nodes": await graph.count_nodes(),
            "edges": await graph.count_edges(),
        }

    @app.get("/methods")
    async def methods(request: Request) -> Any:
        """List every registered JSON-RPC method along with its required scope."""
        principal_or_resp = await _authenticate(request)
        if isinstance(principal_or_resp, JSONResponse):
            return principal_or_resp
        return {
            "count": len(_HANDLERS),
            "methods": [{"method": m, "scope": str(required_scope(m))} for m in sorted(_HANDLERS.keys())],
        }

    @app.get("/metrics")
    async def metrics_endpoint() -> PlainTextResponse:
        """Prometheus-compatible exposition.

        Refreshes the gauge values from the live store so a single
        scrape always reflects current cardinalities, then returns the
        plain-text registry.  No authentication is required because
        Prometheus servers typically scrape from a private network.
        """
        graph: MMapGraphStore = app.state.graph
        try:
            metrics.set("smp_nodes_total", float(await graph.count_nodes()))
            metrics.set("smp_edges_total", float(await graph.count_edges()))
        except Exception:  # noqa: BLE001
            log.exception("metrics_count_failed")
        try:
            metrics.set("smp_sessions_active", float(len(graph._sessions)))  # noqa: SLF001
            metrics.set("smp_locks_active", float(len(graph._locks)))  # noqa: SLF001
            metrics.set(
                "smp_journal_size_bytes",
                float(graph.file.data_region_end - 4096),  # bytes since the start of the data region
            )
        except Exception:  # noqa: BLE001
            log.exception("metrics_internal_state_failed")
        return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")

    @app.post("/admin/backup")
    async def admin_backup(request: Request) -> Any:
        principal_or_resp = await _authenticate(request)
        if isinstance(principal_or_resp, JSONResponse):
            return principal_or_resp
        if not principal_or_resp.has(Scope.ADMIN):
            return JSONResponse(rpc_error(-32002, "Forbidden"), status_code=403)
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            payload = {}
        target = (payload or {}).get("target")
        if not target:
            return JSONResponse(rpc_error(-32602, "missing 'target' path"), status_code=400)
        graph: MMapGraphStore = app.state.graph
        try:
            written = await backup_store(graph, str(target))
        except Exception as exc:  # noqa: BLE001
            log.exception("admin_backup_failed", target=str(target))
            return JSONResponse(rpc_error(-32603, "backup failed", data=str(exc)[:200]), status_code=500)
        return {"backed_up_to": str(written), "bytes": graph.file.size}

    @app.post("/admin/compact")
    async def admin_compact(request: Request) -> Any:
        principal_or_resp = await _authenticate(request)
        if isinstance(principal_or_resp, JSONResponse):
            return principal_or_resp
        if not principal_or_resp.has(Scope.ADMIN):
            return JSONResponse(rpc_error(-32002, "Forbidden"), status_code=403)
        graph: MMapGraphStore = app.state.graph
        try:
            stats = await compact_store(graph)
        except Exception as exc:  # noqa: BLE001
            log.exception("admin_compact_failed")
            return JSONResponse(rpc_error(-32603, "compact failed", data=str(exc)[:200]), status_code=500)
        return {"compacted": True, **stats}

    @app.post("/smp/invalidate")
    async def invalidate(request: Request) -> Any:
        """Tier 3 watcher invalidation — editor plugins call on save.

        Requires the caller to hold the ``write`` scope; an unauthenticated
        client receives ``401`` rather than a silent success.
        """
        principal_or_resp = await _authenticate(request)
        if isinstance(principal_or_resp, JSONResponse):
            return principal_or_resp
        if not principal_or_resp.has(Scope.WRITE):
            return JSONResponse(rpc_error(-32002, "Forbidden"), status_code=403)

        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        file_path = str(payload.get("file_path") or payload.get("path") or "")
        if not file_path:
            return {"invalidated": False, "error": "missing file_path"}

        graph: MMapGraphStore = app.state.graph
        if hasattr(graph, "invalidate_file"):
            await graph.invalidate_file(file_path)
            return {"invalidated": True, "file_path": file_path}
        return {"invalidated": False, "file_path": file_path, "error": "graph store does not support invalidation"}

    return app


# Module-level app for ``uvicorn smp.protocol.server:app`` style invocations.
app = create_app()
