"""Handler for safety protocol methods (session, guard, lock, checkpoint, etc.)."""

from __future__ import annotations

from typing import Any

import msgspec

from smp.core.models import (
    AuditGetParams,
    CheckpointParams,
    DryRunParams,
    GuardCheckParams,
    LockParams,
    RollbackParams,
    SessionCloseParams,
    SessionOpenParams,
    SessionRecoverParams,
)
from smp.engine.integrity import IntegrityCheckResult, IntegrityVerifier
from smp.logging import get_logger
from smp.protocol.handlers.base import MethodHandler

log = get_logger(__name__)


class SessionOpenHandler(MethodHandler):
    """Handles smp/session/open method."""

    @property
    def method(self) -> str:
        return "smp/session/open"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        sop = msgspec.convert(params, SessionOpenParams)
        safety = context.get("safety")
        if not safety:
            raise ValueError("Safety protocol not enabled")

        return await safety["session_manager"].open_session(sop.agent_id, sop.task, sop.scope, sop.mode)


class SessionCloseHandler(MethodHandler):
    """Handles smp/session/close method."""

    @property
    def method(self) -> str:
        return "smp/session/close"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        scp = msgspec.convert(params, SessionCloseParams)
        safety = context.get("safety")
        if not safety:
            raise ValueError("Safety protocol not enabled")

        close_result = await safety["session_manager"].close_session(scp.session_id, scp.status)
        if not close_result:
            raise ValueError(f"Session not found: {scp.session_id}")

        await safety["lock_manager"].release_all(scp.session_id)
        if "audit_logger" in safety:
            safety["audit_logger"].close_log(close_result.get("audit_log_id", ""), scp.status)

        return close_result


class SessionRecoverHandler(MethodHandler):
    """Handles smp/session/recover method."""

    @property
    def method(self) -> str:
        return "smp/session/recover"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        srp = msgspec.convert(params, SessionRecoverParams)
        safety = context.get("safety")
        if not safety:
            raise ValueError("Safety protocol not enabled")

        session_manager = safety.get("session_manager")
        if not session_manager:
            raise ValueError("Session manager not configured")

        result = await session_manager.recover_session(srp.session_id)
        if not result:
            raise ValueError(f"Session not found: {srp.session_id}")

        return result


class GuardCheckHandler(MethodHandler):
    """Handles smp/guard/check method."""

    @property
    def method(self) -> str:
        return "smp/guard/check"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        gcp = msgspec.convert(params, GuardCheckParams)
        safety = context.get("safety")
        if not safety:
            raise ValueError("Safety protocol not enabled")

        return await safety["guard_engine"].check(gcp.session_id, gcp.target, gcp.intended_change)


class DryRunHandler(MethodHandler):
    """Handles smp/dryrun method."""

    @property
    def method(self) -> str:
        return "smp/dryrun"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        drp = msgspec.convert(params, DryRunParams)
        safety = context.get("safety")
        if not safety:
            raise ValueError("Safety protocol not enabled")

        return safety["dryrun_simulator"].simulate(
            drp.session_id, drp.file_path, drp.proposed_content, drp.change_summary
        )


class CheckpointHandler(MethodHandler):
    """Handles smp/checkpoint method."""

    @property
    def method(self) -> str:
        return "smp/checkpoint"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        cp = msgspec.convert(params, CheckpointParams)
        safety = context.get("safety")
        if not safety:
            raise ValueError("Safety protocol not enabled")

        return safety["checkpoint_manager"].create(cp.session_id, cp.files)


class RollbackHandler(MethodHandler):
    """Handles smp/rollback method."""

    @property
    def method(self) -> str:
        return "smp/rollback"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        rbp = msgspec.convert(params, RollbackParams)
        safety = context.get("safety")
        if not safety:
            raise ValueError("Safety protocol not enabled")

        return safety["checkpoint_manager"].rollback(rbp.checkpoint_id)


class LockHandler(MethodHandler):
    """Handles smp/lock method."""

    @property
    def method(self) -> str:
        return "smp/lock"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        lp = msgspec.convert(params, LockParams)
        safety = context.get("safety")
        if not safety:
            raise ValueError("Safety protocol not enabled")

        return await safety["lock_manager"].acquire(lp.session_id, lp.files)


class UnlockHandler(MethodHandler):
    """Handles smp/unlock method."""

    @property
    def method(self) -> str:
        return "smp/unlock"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        ulp = msgspec.convert(params, LockParams)
        safety = context.get("safety")
        if not safety:
            raise ValueError("Safety protocol not enabled")

        await safety["lock_manager"].release(ulp.session_id, ulp.files)
        return {"released": ulp.files}


class AuditGetHandler(MethodHandler):
    """Handles smp/audit/get method."""

    @property
    def method(self) -> str:
        return "smp/audit/get"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        agp = msgspec.convert(params, AuditGetParams)
        safety = context.get("safety")
        if not safety:
            raise ValueError("Safety protocol not enabled")

        audit_logger = safety.get("audit_logger")
        if not audit_logger:
            raise ValueError("Audit logger not configured")

        # Prefer explicit audit_log_id, fall back to session_id param for convenience
        audit = None
        if agp.audit_log_id:
            audit = audit_logger.get_log(agp.audit_log_id)
        if not audit and "session_id" in params:
            audit = audit_logger.get_log_by_session(params.get("session_id"))

        if not audit:
            raise ValueError(f"Audit log not found: {agp.audit_log_id or params.get('session_id')}")

        return audit


class IntegrityVerifyHandler(MethodHandler):
    """Handles smp/verify/integrity method."""

    @property
    def method(self) -> str:
        return "smp/verify/integrity"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        session_id: str = params["session_id"]
        node_ids: list[str] = params.get("node_ids") or []
        mode: str = params.get("mode", "ast")
        if mode not in ("ast", "mutation", "both"):
            raise ValueError(f"Invalid mode: {mode}. Must be 'ast', 'mutation', or 'both'")

        integrity_verifier: IntegrityVerifier | None = context.get("integrity_verifier")
        if not integrity_verifier:
            integrity_verifier = IntegrityVerifier()

        graph_store = context.get("engine")
        all_mutations: list[dict[str, Any]] = []
        all_warnings: list[str] = []
        total_checks = 0
        all_passed = True

        target_ids = node_ids if node_ids else list(integrity_verifier._baselines.keys())

        for nid in target_ids:
            results: list[IntegrityCheckResult] = []

            if mode in ("ast", "both"):
                baseline = integrity_verifier._baselines.get(nid)
                current_state = baseline["state"] if baseline else {}
                ast_result = await integrity_verifier.verify(nid, current_state)
                results.append(ast_result)

            if mode in ("mutation", "both"):
                if not graph_store:
                    all_warnings.append(f"Graph store unavailable for mutation test on {nid}")
                    continue
                mutation_result = await integrity_verifier.run_mutation_test(nid, graph_store)
                results.append(mutation_result)

            for r in results:
                if not r.passed:
                    all_passed = False
                total_checks += r.checks_run
                all_mutations.extend(
                    [
                        {
                            "node_id": m.node_id,
                            "mutation_type": m.mutation_type,
                            "field_name": m.field_name,
                            "old_value": m.old_value,
                            "new_value": m.new_value,
                            "detected_at": m.detected_at,
                        }
                        for m in r.mutations_detected
                    ]
                )
                all_warnings.extend(r.warnings)

        log.info(
            "integrity_verify",
            session_id=session_id,
            mode=mode,
            passed=all_passed,
            checks_run=total_checks,
        )

        return {
            "passed": all_passed,
            "mutations_detected": all_mutations,
            "warnings": all_warnings,
            "checks_run": total_checks,
        }
