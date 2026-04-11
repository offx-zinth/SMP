"""Handoff layer for code review and PR creation.

Manages the transition from AI-generated changes to human review,
including PR creation, review workflows, and approval tracking.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from smp.logging import get_logger

log = get_logger(__name__)


@dataclass
class ReviewRequest:
    """A request for human review."""

    review_id: str
    session_id: str
    files_changed: list[str]
    diff_summary: str
    created_at: str
    status: str = "pending"
    reviewers: list[str] = field(default_factory=list)
    approvals: list[str] = field(default_factory=list)
    rejections: list[str] = field(default_factory=list)
    comments: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PRInfo:
    """Information about a created PR."""

    pr_id: str
    review_id: str
    title: str
    body: str
    branch: str
    base_branch: str
    url: str | None = None
    created_at: str = ""
    status: str = "open"


class HandoffManager:
    """Manages code review and PR workflows."""

    def __init__(self) -> None:
        self._reviews: dict[str, ReviewRequest] = {}
        self._prs: dict[str, PRInfo] = {}

    def create_review(
        self,
        session_id: str,
        files_changed: list[str],
        diff_summary: str,
        reviewers: list[str] | None = None,
    ) -> ReviewRequest:
        """Create a new review request."""
        review_id = f"rev_{uuid.uuid4().hex[:8]}"

        review = ReviewRequest(
            review_id=review_id,
            session_id=session_id,
            files_changed=files_changed,
            diff_summary=diff_summary,
            created_at=datetime.now(UTC).isoformat(),
            reviewers=reviewers or [],
        )
        self._reviews[review_id] = review

        log.info("review_created", review_id=review_id, files=len(files_changed))
        return review

    def add_comment(
        self,
        review_id: str,
        author: str,
        comment: str,
        file_path: str | None = None,
        line: int | None = None,
    ) -> bool:
        """Add a comment to a review."""
        review = self._reviews.get(review_id)
        if not review:
            return False

        comment_data: dict[str, Any] = {
            "author": author,
            "comment": comment,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        if file_path:
            comment_data["file_path"] = file_path
        if line:
            comment_data["line"] = line

        review.comments.append(comment_data)
        log.info("review_comment_added", review_id=review_id, author=author)
        return True

    def approve(self, review_id: str, reviewer: str) -> bool:
        """Record an approval for a review."""
        review = self._reviews.get(review_id)
        if not review:
            return False

        if reviewer not in review.approvals:
            review.approvals.append(reviewer)

        if reviewer in review.rejections:
            review.rejections.remove(reviewer)

        self._update_review_status(review)
        log.info("review_approved", review_id=review_id, reviewer=reviewer)
        return True

    def reject(self, review_id: str, reviewer: str, reason: str = "") -> bool:
        """Record a rejection for a review."""
        review = self._reviews.get(review_id)
        if not review:
            return False

        if reviewer not in review.rejections:
            review.rejections.append(reviewer)

        if reviewer in review.approvals:
            review.approvals.remove(reviewer)

        self._update_review_status(review)
        log.info("review_rejected", review_id=review_id, reviewer=reviewer, reason=reason)
        return True

    def _update_review_status(self, review: ReviewRequest) -> None:
        """Update review status based on approvals/rejections."""
        if len(review.rejections) > 0:
            review.status = "rejected"
        elif len(review.approvals) >= len(review.reviewers) and review.reviewers:
            review.status = "approved"

    def create_pr(
        self,
        review_id: str,
        title: str,
        body: str,
        branch: str,
        base_branch: str = "main",
    ) -> PRInfo | None:
        """Create a PR for an approved review."""
        review = self._reviews.get(review_id)
        if not review:
            return None

        pr_id = f"pr_{uuid.uuid4().hex[:8]}"

        pr = PRInfo(
            pr_id=pr_id,
            review_id=review_id,
            title=title,
            body=body,
            branch=branch,
            base_branch=base_branch,
            created_at=datetime.now(UTC).isoformat(),
        )
        self._prs[pr_id] = pr

        review.status = "pr_created"
        log.info("pr_created", pr_id=pr_id, review_id=review_id)
        return pr

    def get_review(self, review_id: str) -> ReviewRequest | None:
        """Get review by ID."""
        return self._reviews.get(review_id)

    def get_pr(self, pr_id: str) -> PRInfo | None:
        """Get PR by ID."""
        return self._prs.get(pr_id)

    def list_pending_reviews(self) -> list[ReviewRequest]:
        """List all pending reviews."""
        return [r for r in self._reviews.values() if r.status == "pending"]

    def get_review_summary(self, review_id: str) -> dict[str, Any] | None:
        """Get summary of a review."""
        review = self._reviews.get(review_id)
        if not review:
            return None

        return {
            "review_id": review.review_id,
            "session_id": review.session_id,
            "status": review.status,
            "files_count": len(review.files_changed),
            "reviewers": len(review.reviewers),
            "approvals": len(review.approvals),
            "rejections": len(review.rejections),
            "comments_count": len(review.comments),
        }
