"""Handler for handoff and review methods."""

from __future__ import annotations

from typing import Any

import msgspec
from smp.core.models import PRCreateParams, ReviewCreateParams
from smp.protocol.handlers.base import MethodHandler


class HandoffReviewHandler(MethodHandler):
    """Handles smp/handoff/review method."""

    @property
    def method(self) -> str:
        return "smp/handoff/review"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        p = msgspec.convert(params, ReviewCreateParams)
        manager = context["handoff_manager"]
        review = manager.create_review(
            session_id=p.session_id,
            files_changed=p.files_changed,
            diff_summary=p.diff_summary,
            reviewers=p.reviewers,
        )
        return {
            "review_id": review.review_id,
            "status": review.status,
            "created_at": review.created_at,
        }


class HandoffApproveHandler(MethodHandler):
    """Handles smp/handoff/approve method."""

    @property
    def method(self) -> str:
        return "smp/handoff/approve"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        review_id = params.get("review_id")
        reviewer = params.get("reviewer")
        if not review_id or not reviewer:
            raise ValueError("review_id and reviewer are required")

        manager = context["handoff_manager"]
        success = manager.approve(review_id, reviewer)
        if not success:
            raise ValueError(f"Review not found: {review_id}")

        review = manager.get_review(review_id)
        return {
            "review_id": review_id,
            "status": review.status if review else "unknown",
            "approved_by": reviewer,
        }


class HandoffRejectHandler(MethodHandler):
    """Handles smp/handoff/reject method."""

    @property
    def method(self) -> str:
        return "smp/handoff/reject"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        review_id = params.get("review_id")
        reviewer = params.get("reviewer")
        reason = params.get("reason", "")
        if not review_id or not reviewer:
            raise ValueError("review_id and reviewer are required")

        manager = context["handoff_manager"]
        success = manager.reject(review_id, reviewer, reason)
        if not success:
            raise ValueError(f"Review not found: {review_id}")

        review = manager.get_review(review_id)
        return {
            "review_id": review_id,
            "status": review.status if review else "unknown",
            "rejected_by": reviewer,
            "reason": reason,
        }


class HandoffPRHandler(MethodHandler):
    """Handles smp/handoff/pr method."""

    @property
    def method(self) -> str:
        return "smp/handoff/pr"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        p = msgspec.convert(params, PRCreateParams)
        manager = context["handoff_manager"]
        pr = manager.create_pr(
            review_id=p.review_id,
            title=p.title,
            body=p.body,
            branch=p.branch,
            base_branch=p.base_branch,
        )
        if pr is None:
            return None
        return {
            "pr_id": pr.pr_id,
            "status": pr.status,
            "url": pr.url,
            "created_at": pr.created_at,
        }
