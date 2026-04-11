"""JSON-RPC 2.0 dispatcher for the Structural Memory Protocol (SMP(3)).

All SMP protocol methods are routed through a single ``POST /rpc`` endpoint.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import msgspec
from fastapi import Request
from fastapi.responses import Response

from smp.core.models import (
    AnnotateBulkParams,
    AnnotateParams,
    AuditGetParams,
    BatchUpdateParams,
    CheckpointParams,
    ContextParams,
    DryRunParams,
    EnrichBatchParams,
    EnrichParams,
    EnrichStaleParams,
    EnrichStatusParams,
    FlowParams,
    GuardCheckParams,
    ImpactParams,
    IntegrityCheckParams,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
    LocateParams,
    LockParams,
    NavigateParams,
    PRCreateParams,
    ReindexParams,
    ReviewApproveParams,
    ReviewCommentParams,
    ReviewCreateParams,
    ReviewRejectParams,
    RollbackParams,
    SearchParams,
    SessionCloseParams,
    SessionOpenParams,
    TagParams,
    TelemetryParams,
    TraceParams,
    UpdateParams,
)
from smp.logging import get_logger
from smp.sandbox.executor import SandboxExecutor

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


async def _handle_update(
    params: dict[str, Any],
    engine: Any,
    enricher: Any,
    builder: Any,
    registry: Any,
    vector: Any,
) -> dict[str, Any]:
    p = msgspec.convert(params, UpdateParams)
    file_path = p.file_path

    if p.content:
        parser_obj = registry.get(p.language)
        if not parser_obj:
            from smp.core.models import Language

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

    return {
        "file_path": file_path,
        "nodes": len(doc.nodes),
        "edges": len(doc.edges),
        "errors": len(doc.errors),
    }


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
    runtime_linker: Any = None,
) -> Response:
    """Dispatch a single JSON-RPC 2.0 request."""

    # Build context for handlers
    context: dict[str, Any] = {
        "engine": engine,
        "enricher": enricher,
        "builder": builder,
        "registry": registry,
        "vector": vector,
        "safety": safety,
        "telemetry_engine": telemetry_engine,
        "handoff_manager": handoff_manager,
        "integrity_verifier": integrity_verifier,
        "runtime_linker": runtime_linker,
    }
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
    params = req.params

    log.debug("rpc_request", method=method, id=req.id)

    try:
        # --- Memory Management ---
        if method == "smp/update":
            result = await _handle_update(params, engine, enricher, builder, registry, vector)

        elif method == "smp/batch_update":
            bp = msgspec.convert(params, BatchUpdateParams)
            results = []
            for change in bp.changes:
                r = await _handle_update(change, engine, enricher, builder, registry, vector)
                results.append(r)
            result = {"updates": len(results), "results": results}

        elif method == "smp/reindex":
            rp = msgspec.convert(params, ReindexParams)
            result = {"status": "reindex_requested", "scope": rp.scope}

        # --- Enrichment ---
        elif method == "smp/enrich":
            ep = msgspec.convert(params, EnrichParams)
            node = await engine._graph.get_node(ep.node_id)
            if not node:
                return _error_response(req.id, -32001, "Node not found", data={"node_id": ep.node_id})
            enriched = await enricher.enrich_node(node, force=ep.force)
            if enriched.semantic.source_hash and enriched.semantic.status == "enriched":
                await engine._graph.upsert_node(enriched)
            result = {
                "node_id": enriched.id,
                "status": enriched.semantic.status,
                "docstring": enriched.semantic.docstring,
                "inline_comments": [{"line": c.line, "text": c.text} for c in enriched.semantic.inline_comments],
                "decorators": enriched.semantic.decorators,
                "annotations": {
                    "params": enriched.semantic.annotations.params if enriched.semantic.annotations else {},
                    "returns": enriched.semantic.annotations.returns if enriched.semantic.annotations else None,
                    "throws": enriched.semantic.annotations.throws if enriched.semantic.annotations else [],
                }
                if enriched.semantic.annotations
                else {},
                "tags": enriched.semantic.tags,
                "source_hash": enriched.semantic.source_hash,
                "enriched_at": enriched.semantic.enriched_at,
            }

        elif method == "smp/enrich/batch":
            ebp = msgspec.convert(params, EnrichBatchParams)
            nodes = await engine._graph.find_nodes_by_scope(ebp.scope)
            enriched_count = 0
            skipped_count = 0
            no_metadata_count = 0
            no_metadata_nodes: list[str] = []
            for node in nodes:
                enriched = await enricher.enrich_node(node, force=ebp.force)
                if enriched.semantic.status == "enriched":
                    enriched_count += 1
                    await engine._graph.upsert_node(enriched)
                elif enriched.semantic.status == "skipped":
                    skipped_count += 1
                elif enriched.semantic.status == "no_metadata":
                    no_metadata_count += 1
                    no_metadata_nodes.append(enriched.id)
            result = {
                "enriched": enriched_count,
                "skipped": skipped_count,
                "no_metadata": no_metadata_count,
                "failed": 0,
                "no_metadata_nodes": no_metadata_nodes,
            }

        elif method == "smp/enrich/stale":
            esp = msgspec.convert(params, EnrichStaleParams)
            nodes = await engine._graph.find_nodes_by_scope(esp.scope)
            stale_nodes = []
            for node in nodes:
                if node.semantic.source_hash:
                    from smp.engine.enricher import _compute_source_hash

                    current = _compute_source_hash(
                        node.structural.name,
                        node.file_path,
                        node.structural.start_line,
                        node.structural.end_line,
                        node.structural.signature,
                    )
                    if current != node.semantic.source_hash:
                        stale_nodes.append(
                            {
                                "node_id": node.id,
                                "file": node.file_path,
                                "last_enriched": node.semantic.enriched_at,
                                "current_hash": current,
                                "enriched_hash": node.semantic.source_hash,
                            }
                        )
            result = {"stale_count": len(stale_nodes), "stale_nodes": stale_nodes}

        elif method == "smp/enrich/status":
            estp = msgspec.convert(params, EnrichStatusParams)
            nodes = await engine._graph.find_nodes_by_scope(estp.scope)
            total = len(nodes)
            has_docstring = sum(1 for n in nodes if n.semantic.docstring)
            has_annotations = sum(
                1
                for n in nodes
                if n.semantic.annotations and (n.semantic.annotations.params or n.semantic.annotations.returns)
            )
            has_tags = sum(1 for n in nodes if n.semantic.tags)
            manually_annotated = sum(1 for n in nodes if n.semantic.manually_set)
            no_metadata = sum(1 for n in nodes if n.semantic.status == "no_metadata")
            coverage = round((total - no_metadata) / total * 100, 1) if total > 0 else 0
            result = {
                "total_nodes": total,
                "has_docstring": has_docstring,
                "has_annotations": has_annotations,
                "has_tags": has_tags,
                "manually_annotated": manually_annotated,
                "no_metadata": no_metadata,
                "stale": 0,
                "coverage_pct": coverage,
            }

        # --- Annotation ---
        elif method == "smp/annotate":
            ap = msgspec.convert(params, AnnotateParams)
            node = await engine._graph.get_node(ap.node_id)
            if not node:
                return _error_response(req.id, -32001, "Node not found", data={"node_id": ap.node_id})
            if node.semantic.docstring and not ap.force:
                return _error_response(
                    req.id,
                    -32002,
                    "Node already has extracted docstring. Set force: true to override.",
                    data={"node_id": ap.node_id},
                )
            node.semantic.description = ap.description
            node.semantic.tags = list(set(node.semantic.tags + ap.tags))
            node.semantic.manually_set = True
            node.semantic.status = "manually_annotated"
            node.semantic.enriched_at = datetime.now(UTC).isoformat()
            await engine._graph.upsert_node(node)
            result = {
                "node_id": ap.node_id,
                "status": "annotated",
                "manually_set": True,
                "annotated_at": node.semantic.enriched_at,
            }

        elif method == "smp/annotate/bulk":
            abp = msgspec.convert(params, AnnotateBulkParams)
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
            result = {"annotated": annotated, "failed": failed}

        elif method == "smp/tag":
            tp = msgspec.convert(params, TagParams)
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
            result = {"nodes_affected": affected, "action": tp.action, "scope": tp.scope}

        # --- Safety ---
        elif method == "smp/session/open":
            sop = msgspec.convert(params, SessionOpenParams)
            if not safety:
                return _error_response(req.id, -32601, "Safety protocol not enabled")
            result = await safety["session_manager"].open_session(sop.agent_id, sop.task, sop.scope, sop.mode)

        elif method == "smp/session/close":
            scp = msgspec.convert(params, SessionCloseParams)
            if not safety:
                return _error_response(req.id, -32601, "Safety protocol not enabled")
            close_result = await safety["session_manager"].close_session(scp.session_id, scp.status)
            if close_result:
                safety["lock_manager"].release_all(scp.session_id)
                if "audit_logger" in safety:
                    safety["audit_logger"].close_log(close_result.get("audit_log_id", ""), scp.status)
                result = close_result
            else:
                return _error_response(req.id, -32001, "Session not found", data={"session_id": scp.session_id})

        elif method == "smp/guard/check":
            gcp = msgspec.convert(params, GuardCheckParams)
            if not safety:
                return _error_response(req.id, -32601, "Safety protocol not enabled")
            result = await safety["guard_engine"].check(gcp.session_id, gcp.target, gcp.intended_change)

        elif method == "smp/dryrun":
            drp = msgspec.convert(params, DryRunParams)
            if not safety:
                return _error_response(req.id, -32601, "Safety protocol not enabled")
            result = safety["dryrun_simulator"].simulate(
                drp.session_id, drp.file_path, drp.proposed_content, drp.change_summary
            )

        elif method == "smp/checkpoint":
            cp = msgspec.convert(params, CheckpointParams)
            if not safety:
                return _error_response(req.id, -32601, "Safety protocol not enabled")
            result = safety["checkpoint_manager"].create(cp.session_id, cp.files)

        elif method == "smp/rollback":
            rbp = msgspec.convert(params, RollbackParams)
            if not safety:
                return _error_response(req.id, -32601, "Safety protocol not enabled")
            result = safety["checkpoint_manager"].rollback(rbp.checkpoint_id)

        elif method == "smp/lock":
            lp = msgspec.convert(params, LockParams)
            if not safety:
                return _error_response(req.id, -32601, "Safety protocol not enabled")
            result = await safety["lock_manager"].acquire(lp.session_id, lp.files)

        elif method == "smp/unlock":
            ulp = msgspec.convert(params, LockParams)
            if not safety:
                return _error_response(req.id, -32601, "Safety protocol not enabled")
            await safety["lock_manager"].release(ulp.session_id, ulp.files)
            result = {"released": ulp.files}

        elif method == "smp/audit/get":
            agp = msgspec.convert(params, AuditGetParams)
            if not safety:
                return _error_response(req.id, -32601, "Safety protocol not enabled")
            audit = safety["audit_logger"].get_log(agp.audit_log_id)
            if not audit:
                return _error_response(req.id, -32001, "Audit log not found", data={"audit_log_id": agp.audit_log_id})
            result = audit

        # --- Query ---
        elif method == "smp/navigate":
            np_ = msgspec.convert(params, NavigateParams)
            result = await engine.navigate(np_.query, np_.include_relationships)

        elif method == "smp/trace":
            trp = msgspec.convert(params, TraceParams)
            result = await engine.trace(trp.start, trp.relationship, trp.depth, trp.direction)

        elif method == "smp/context":
            ctp = msgspec.convert(params, ContextParams)
            result = await engine.get_context(ctp.file_path, ctp.scope, ctp.depth)

        elif method == "smp/impact":
            imp = msgspec.convert(params, ImpactParams)
            result = await engine.assess_impact(imp.entity, imp.change_type)

        elif method == "smp/locate":
            loc = msgspec.convert(params, LocateParams)
            result = await engine.locate(loc.query, loc.fields, loc.node_types, loc.top_k)

        elif method == "smp/search":
            sp = msgspec.convert(params, SearchParams)
            result = await engine.search(sp.query, sp.match, sp.filter, sp.top_k)

        elif method == "smp/flow":
            fp = msgspec.convert(params, FlowParams)
            result = await engine.find_flow(fp.start, fp.end, fp.flow_type)

        elif method == "smp/graph/why":
            wp = msgspec.convert(params, dict)
            result = await engine.why(
                entity=wp.get("entity", ""),
                relationship=wp.get("relationship", ""),
                depth=wp.get("depth", 3),
            )

        elif method == "smp/diff":
            dp = msgspec.convert(params, dict)
            result = await engine.diff_file(
                file_path=dp.get("file_path", ""),
                proposed_content=dp.get("proposed_content"),
            )

        elif method == "smp/plan":
            pp = msgspec.convert(params, dict)
            result = await engine.plan_multi_file(
                session_id=pp.get("session_id", ""),
                task=pp.get("task", ""),
                intended_writes=pp.get("intended_writes", []),
            )

        elif method == "smp/conflict":
            cp = msgspec.convert(params, dict)
            result = await engine.detect_conflict(
                session_a=cp.get("session_a", ""),
                session_b=cp.get("session_b", ""),
            )

        # --- Sandbox ---
        elif method == "smp/sandbox/spawn":
            if not safety:
                return _error_response(req.id, -32601, "Sandbox functionality requires safety protocol")
            result = safety["sandbox_spawner"].spawn(
                name=params.get("name"), template=params.get("template"), files=params.get("files")
            )
            result = {
                "sandbox_id": result.sandbox_id,
                "root_path": result.root_path,
                "created_at": result.created_at,
                "status": result.status,
            }
        elif method == "smp/sandbox/execute":
            if not safety:
                return _error_response(req.id, -32601, "Sandbox functionality requires safety protocol")
            sep = msgspec.convert(params, dict)
            executor = safety.get("sandbox_executor")
            if not executor:
                # Create a default executor if not in context
                executor = SandboxExecutor()
            result = await executor.execute(
                command=sep.get("command", []), stdin=sep.get("stdin"), cwd=sep.get("working_directory")
            )
            result = {
                "execution_id": result.execution_id,
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration_ms": result.duration_ms,
                "memory_used_mb": result.memory_used_mb,
                "timed_out": result.timed_out,
                "killed": result.killed,
                "metadata": result.metadata,
            }
        elif method == "smp/sandbox/destroy":
            if not safety:
                return _error_response(req.id, -32601, "Sandbox functionality requires safety protocol")
            sdp = msgspec.convert(params, dict)
            sandbox_id = sdp.get("sandbox_id")
            if not sandbox_id:
                return _error_response(req.id, -32602, "sandbox_id is required")
            destroyed = safety["sandbox_spawner"].destroy(sandbox_id)
            if destroyed:
                result = {
                    "sandbox_id": sandbox_id,
                    "status": "destroyed",
                    "destroyed_at": datetime.now(UTC).isoformat(),
                }
            else:
                result = {"error": f"Sandbox not found: {sandbox_id}"}

        # --- Telemetry ---
        elif method == "smp/telemetry":
            tp = msgspec.convert(params, TelemetryParams)
            telemetry_engine = context.get("telemetry_engine")
            if not telemetry_engine:
                result = {"action": tp.action, "status": "not_configured"}
            elif tp.action == "get_stats":
                result = telemetry_engine.get_summary()
            elif tp.action == "get_hot" and tp.node_id:
                result = telemetry_engine.get_stats(tp.node_id)
            elif tp.action == "decay":
                result = {"decayed": telemetry_engine.decay()}
            else:
                result = {"error": "Unknown telemetry action"}

        # --- Runtime Linker ---
        elif method == "smp/linker/report":
            linker = context.get("runtime_linker")
            if not linker:
                result = {"unresolved_edges": [], "status": "not_configured"}
            else:
                pending_count = linker.get_pending_count()
                result = {"unresolved_edges": [], "pending_count": pending_count, "status": "ok"}
        elif method == "smp/linker/runtime":
            linker = context.get("runtime_linker")
            if not linker:
                result = {"hot_paths": [], "status": "not_configured"}
            else:
                threshold = params.get("threshold", 10)
                result = {"hot_paths": linker.get_hot_paths(threshold), "stats": linker.get_stats()}

        # --- Handoff ---
        elif method == "smp/handoff/review":
            rcp = msgspec.convert(params, ReviewCreateParams)
            handoff_manager = context.get("handoff_manager")
            if not handoff_manager:
                result = {"error": "Handoff manager not configured"}
            else:
                review = handoff_manager.create_review(
                    session_id=rcp.session_id,
                    files_changed=rcp.files_changed,
                    diff_summary=rcp.diff_summary,
                    reviewers=rcp.reviewers,
                )
                result = {"review_id": review.review_id, "status": review.status, "created_at": review.created_at}
        elif method == "smp/handoff/review/comment":
            rcm = msgspec.convert(params, ReviewCommentParams)
            handoff_manager = context.get("handoff_manager")
            if not handoff_manager:
                result = {"error": "Handoff manager not configured"}
            else:
                success = handoff_manager.add_comment(
                    review_id=rcm.review_id,
                    author=rcm.author,
                    comment=rcm.comment,
                    file_path=rcm.file_path,
                    line=rcm.line,
                )
                result = {"success": success, "review_id": rcm.review_id}
        elif method == "smp/handoff/review/approve":
            rap = msgspec.convert(params, ReviewApproveParams)
            handoff_manager = context.get("handoff_manager")
            if not handoff_manager:
                result = {"error": "Handoff manager not configured"}
            else:
                success = handoff_manager.approve(rap.review_id, rap.reviewer)
                result = {"success": success, "review_id": rap.review_id, "status": "approved" if success else "failed"}
        elif method == "smp/handoff/review/reject":
            rrj = msgspec.convert(params, ReviewRejectParams)
            handoff_manager = context.get("handoff_manager")
            if not handoff_manager:
                result = {"error": "Handoff manager not configured"}
            else:
                success = handoff_manager.reject(rrj.review_id, rrj.reviewer, rrj.reason)
                result = {"success": success, "review_id": rrj.review_id, "status": "rejected" if success else "failed"}
        elif method == "smp/handoff/pr":
            pcp = msgspec.convert(params, PRCreateParams)
            handoff_manager = context.get("handoff_manager")
            if not handoff_manager:
                result = {"error": "Handoff manager not configured"}
            else:
                pr = handoff_manager.create_pr(
                    review_id=pcp.review_id,
                    title=pcp.title,
                    body=pcp.body,
                    branch=pcp.branch,
                    base_branch=pcp.base_branch,
                )
                if pr:
                    result = {"pr_id": pr.pr_id, "status": pr.status, "created_at": pr.created_at, "url": pr.url}
                else:
                    result = {"error": "Review not found or not approved"}

        # --- Integrity ---
        elif method == "smp/verify/integrity":
            icp = msgspec.convert(params, IntegrityCheckParams)
            verifier = context.get("integrity_verifier")
            if not verifier:
                result = {"status": "not_configured", "error": "Integrity verifier not available"}
            else:
                result = await verifier.verify(icp.node_id, icp.current_state)

        else:
            return _error_response(req.id, -32601, f"Method not found: {method}")

    except msgspec.ValidationError as exc:
        return _error_response(req.id, -32602, f"Invalid params: {exc}")
    except Exception as exc:
        log.error("rpc_internal_error", method=method, error=str(exc))
        return _error_response(req.id, -32603, f"Internal error: {exc}")

    if req.id is None:
        return Response(content=b"", status_code=204)

    return _success_response(req.id, result)
