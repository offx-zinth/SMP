"""Code review and PR handlers (smp/review/*, smp/pr/create).

Reviews are stored as durable session records via
``graph.upsert_session``.  Pull-request creation is delegated to the
configured :class:`smp.runtime.git_provider.GitProvider`, which is
selected from environment variables at server start (defaulting to
``NullGitProvider`` when nothing is configured — useful for offline /
demo runs).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import msgspec

from smp.core.models import (
    PRCreateParams,
    ReviewApproveParams,
    ReviewCommentParams,
    ReviewCreateParams,
    ReviewRejectParams,
)
from smp.logging import get_logger
from smp.runtime.git_provider import get_provider

log = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _review_store(ctx: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return ctx.setdefault("_reviews", {})  # type: ignore[no-any-return]


def _pr_store(ctx: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return ctx.setdefault("_pull_requests", {})  # type: ignore[no-any-return]


async def _persist(graph: Any, record: dict[str, Any]) -> None:
    try:
        await graph.upsert_session(record)
    except (NotImplementedError, AttributeError):
        return


async def review_create(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/review/create``."""
    p = msgspec.convert(params, ReviewCreateParams)
    graph = ctx["graph"]

    import uuid as _uuid

    review_id = f"rev_{_uuid.uuid4().hex[:12]}"
    record = {
        "session_id": review_id,
        "review_id": review_id,
        "kind": "review",
        "session": p.session_id,
        "files_changed": list(p.files_changed),
        "diff_summary": p.diff_summary,
        "reviewers": list(p.reviewers),
        "status": "pending",
        "comments": [],
        "approvals": [],
        "rejections": [],
        "created_at": _now_iso(),
    }
    _review_store(ctx)[review_id] = record
    await _persist(graph, record)

    return {
        "review_id": review_id,
        "status": "pending",
        "files_changed": record["files_changed"],
        "reviewers": record["reviewers"],
    }


async def review_approve(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/review/approve``."""
    p = msgspec.convert(params, ReviewApproveParams)
    graph = ctx["graph"]

    review = _review_store(ctx).get(p.review_id)
    if review is None:
        return {"review_id": p.review_id, "approved": False, "error": "review_not_found"}

    review.setdefault("approvals", []).append({"reviewer": p.reviewer, "ts": _now_iso()})
    if review["approvals"] and not review.get("rejections"):
        review["status"] = "approved"
    await _persist(graph, review)

    return {
        "review_id": p.review_id,
        "approved": True,
        "status": review["status"],
        "approvals": review["approvals"],
    }


async def review_reject(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/review/reject``."""
    p = msgspec.convert(params, ReviewRejectParams)
    graph = ctx["graph"]

    review = _review_store(ctx).get(p.review_id)
    if review is None:
        return {"review_id": p.review_id, "rejected": False, "error": "review_not_found"}

    review.setdefault("rejections", []).append(
        {"reviewer": p.reviewer, "reason": p.reason, "ts": _now_iso()}
    )
    review["status"] = "rejected"
    await _persist(graph, review)

    return {
        "review_id": p.review_id,
        "rejected": True,
        "status": review["status"],
        "rejections": review["rejections"],
    }


async def review_comment(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/review/comment``."""
    p = msgspec.convert(params, ReviewCommentParams)
    graph = ctx["graph"]

    review = _review_store(ctx).get(p.review_id)
    if review is None:
        return {"review_id": p.review_id, "added": False, "error": "review_not_found"}

    comment = {
        "author": p.author,
        "comment": p.comment,
        "file_path": p.file_path,
        "line": p.line,
        "ts": _now_iso(),
    }
    review.setdefault("comments", []).append(comment)
    await _persist(graph, review)

    return {"review_id": p.review_id, "added": True, "comment": comment, "total_comments": len(review["comments"])}


async def pr_create(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle ``smp/pr/create``.

    Delegates the actual PR creation to the configured
    :class:`smp.runtime.git_provider.GitProvider`.  The handler still
    persists a session record so that downstream review / audit code
    can correlate the PR back to the review that produced it.
    """
    p = msgspec.convert(params, PRCreateParams)
    graph = ctx["graph"]
    provider = get_provider(ctx)

    review = _review_store(ctx).get(p.review_id)
    if p.review_id and review is None:
        return {"pr_id": "", "created": False, "error": "review_not_found"}

    try:
        pr = await provider.create_pull_request(
            title=p.title,
            body=p.body,
            branch=p.branch,
            base_branch=p.base_branch or "main",
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("pr_create_failed", provider=provider.name)
        return {
            "pr_id": "",
            "created": False,
            "provider": provider.name,
            "error": "git_provider_error",
            "detail": str(exc)[:200],
        }

    record = {
        "session_id": pr.pr_id,
        "pr_id": pr.pr_id,
        "kind": "pr",
        "review_id": p.review_id,
        "title": pr.title,
        "body": pr.body,
        "branch": pr.branch,
        "base_branch": pr.base_branch,
        "provider": pr.provider,
        "url": pr.url,
        "number": pr.number,
        "status": "open",
        "created_at": pr.created_at or _now_iso(),
    }
    _pr_store(ctx)[pr.pr_id] = record
    await _persist(graph, record)

    if review is not None:
        review.setdefault("pull_requests", []).append(pr.pr_id)
        await _persist(graph, review)

    return {
        "pr_id": pr.pr_id,
        "created": True,
        "status": "open",
        "branch": pr.branch,
        "base_branch": pr.base_branch,
        "provider": pr.provider,
        "url": pr.url,
        "number": pr.number,
    }


__all__ = [
    "pr_create",
    "review_approve",
    "review_comment",
    "review_create",
    "review_reject",
]
