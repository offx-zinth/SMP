"""Pluggable Git provider adapters for ``smp/pr/create``.

Two implementations are shipped:

``LocalGitProvider``
    A real Git client (uses the system ``git`` executable) that creates
    a branch and commits in a configured working tree.  This is what
    runs in CI / local development and is the integration path that
    every test exercises.

``GitHubProvider``
    Hits the GitHub REST API to open a real pull request.  Requires
    an authenticated token in ``GITHUB_TOKEN`` and the repo's
    ``owner/name`` slug.  No external HTTP is performed unless
    explicitly invoked, so the unit tests don't need network access.

Selection is environment-driven (see :func:`provider_from_env`):

* ``SMP_GIT_PROVIDER=local``  + ``SMP_LOCAL_REPO=<path>`` →
  :class:`LocalGitProvider`
* ``SMP_GIT_PROVIDER=github`` + ``SMP_GITHUB_REPO=<owner/repo>`` and
  ``SMP_GITHUB_TOKEN`` (or ``GITHUB_TOKEN``) → :class:`GitHubProvider`
* No ``SMP_GIT_PROVIDER`` → :class:`NullGitProvider` which records the
  request without executing it.
"""

from __future__ import annotations

import abc
import json
import os
import subprocess
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from smp.logging import get_logger

log = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PullRequestRecord:
    """A successful PR creation result returned by every provider."""

    pr_id: str
    provider: str
    title: str
    body: str
    branch: str
    base_branch: str
    url: str = ""
    number: int | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pr_id": self.pr_id,
            "provider": self.provider,
            "title": self.title,
            "body": self.body,
            "branch": self.branch,
            "base_branch": self.base_branch,
            "url": self.url,
            "number": self.number,
            "created_at": self.created_at or _now_iso(),
        }


class GitProvider(abc.ABC):
    """Abstract Git provider used by the PR handler."""

    name: str = "abstract"

    @abc.abstractmethod
    async def create_pull_request(
        self,
        *,
        title: str,
        body: str,
        branch: str,
        base_branch: str,
        files: dict[str, str] | None = None,
    ) -> PullRequestRecord:
        """Open a pull request and return the resulting record."""


# ---------------------------------------------------------------------------
# Null provider — used when no integration is configured.
# ---------------------------------------------------------------------------


class NullGitProvider(GitProvider):
    """Provider that records intent but does not touch any Git host.

    Useful for environments where SMP runs without external connectivity
    (offline demos, smoke tests, sandbox CI without secrets).  Returns a
    deterministic synthetic ``pr_id`` so callers can integrate with the
    rest of the review flow.
    """

    name = "null"

    async def create_pull_request(
        self,
        *,
        title: str,
        body: str,
        branch: str,
        base_branch: str,
        files: dict[str, str] | None = None,
    ) -> PullRequestRecord:
        del files
        pr_id = f"pr_{uuid.uuid4().hex[:10]}"
        return PullRequestRecord(
            pr_id=pr_id,
            provider=self.name,
            title=title,
            body=body,
            branch=branch,
            base_branch=base_branch or "main",
            url=f"smp://null/{pr_id}",
            created_at=_now_iso(),
        )


# ---------------------------------------------------------------------------
# Local provider — drives the system ``git`` binary.
# ---------------------------------------------------------------------------


class LocalGitProvider(GitProvider):
    """Real Git provider that operates on a local working tree.

    Each call:

    1. Switches to (or creates) ``branch`` from ``base_branch``.
    2. Optionally writes ``files`` and stages them.
    3. Commits with the supplied title/body when there are changes.
    4. Returns a :class:`PullRequestRecord` whose ``url`` points at the
       branch (no remote push is attempted).

    The provider never pushes — pushing is a deployment-policy decision
    that belongs to the host system.  The branch / commit on disk is the
    artifact this provider produces.
    """

    name = "local"

    def __init__(self, repo_path: str | Path, *, author: str = "smp <smp@local>") -> None:
        self.repo = Path(repo_path).resolve()
        if not (self.repo / ".git").exists():
            raise FileNotFoundError(f"not a git repo: {self.repo}")
        self.author = author

    async def create_pull_request(
        self,
        *,
        title: str,
        body: str,
        branch: str,
        base_branch: str,
        files: dict[str, str] | None = None,
    ) -> PullRequestRecord:
        import asyncio

        base = base_branch or "main"
        return await asyncio.to_thread(
            self._run, title=title, body=body, branch=branch, base_branch=base, files=files or {}
        )

    def _run(
        self,
        *,
        title: str,
        body: str,
        branch: str,
        base_branch: str,
        files: dict[str, str],
    ) -> PullRequestRecord:
        # Resolve base.  If the branch already exists, switch to it; else create.
        self._git("fetch", "--quiet", check=False)
        existing = self._git("rev-parse", "--verify", branch, check=False)
        if existing.returncode == 0:
            self._git("checkout", branch)
        else:
            self._git("checkout", "-b", branch, base_branch)

        for rel, content in files.items():
            target = (self.repo / rel).resolve()
            if self.repo not in target.parents and target != self.repo:
                raise ValueError(f"path escapes repository: {rel!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            self._git("add", rel)

        # Only commit if there's something staged.
        status = self._git("status", "--porcelain")
        if status.stdout.strip():
            message = title if not body else f"{title}\n\n{body}"
            self._git(
                "-c", f"user.email={self.author.split('<')[-1].rstrip('>').strip() or 'smp@local'}",
                "-c", f"user.name={self.author.split('<')[0].strip() or 'smp'}",
                "commit", "-m", message,
            )

        rev = self._git("rev-parse", "HEAD").stdout.strip()
        pr_id = f"pr_{uuid.uuid4().hex[:10]}"
        return PullRequestRecord(
            pr_id=pr_id,
            provider=self.name,
            title=title,
            body=body,
            branch=branch,
            base_branch=base_branch,
            url=f"local://{self.repo}/{branch}@{rev[:8]}",
            created_at=_now_iso(),
        )

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            check=False,
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result


# ---------------------------------------------------------------------------
# GitHub provider — talks to the public REST API.
# ---------------------------------------------------------------------------


class GitHubProvider(GitProvider):
    """GitHub REST v3 ``POST /repos/{owner}/{repo}/pulls`` adapter.

    The provider is intentionally minimal: it expects the branch to
    already exist on the remote (a separate push step is the operator's
    responsibility) and just opens the PR.  This keeps the surface easy
    to mock in tests and avoids smuggling write-access secrets into
    paths that don't need them.
    """

    name = "github"
    api_base = "https://api.github.com"

    def __init__(self, *, repo: str, token: str, opener: Any | None = None) -> None:
        if "/" not in repo:
            raise ValueError(f"expected owner/name, got {repo!r}")
        self.repo = repo
        self.token = token
        self._opener = opener  # injectable for tests

    async def create_pull_request(
        self,
        *,
        title: str,
        body: str,
        branch: str,
        base_branch: str,
        files: dict[str, str] | None = None,
    ) -> PullRequestRecord:
        del files  # GitHub PR open assumes the branch is pushed.
        import asyncio

        return await asyncio.to_thread(
            self._post_pull, title=title, body=body, branch=branch, base_branch=base_branch or "main"
        )

    def _post_pull(self, *, title: str, body: str, branch: str, base_branch: str) -> PullRequestRecord:
        url = f"{self.api_base}/repos/{self.repo}/pulls"
        data = json.dumps({"title": title, "body": body, "head": branch, "base": base_branch}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "smp-protocol",
            },
        )
        opener = self._opener or urllib.request.build_opener()
        try:
            response = opener.open(req, timeout=15.0)
            payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"GitHub API error {exc.code}: {exc.read().decode('utf-8', 'replace')}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"GitHub API unreachable: {exc.reason}") from exc

        return PullRequestRecord(
            pr_id=f"gh_{payload.get('number')}",
            provider=self.name,
            title=title,
            body=body,
            branch=branch,
            base_branch=base_branch,
            url=str(payload.get("html_url", "")),
            number=int(payload.get("number")) if payload.get("number") else None,
            created_at=str(payload.get("created_at") or _now_iso()),
        )


# ---------------------------------------------------------------------------
# Selection helpers
# ---------------------------------------------------------------------------


def provider_from_env() -> GitProvider:
    """Build a Git provider from environment configuration.

    Falls back to :class:`NullGitProvider` if nothing is configured so
    handlers can always rely on the abstraction being non-``None``.
    """
    kind = (os.environ.get("SMP_GIT_PROVIDER") or "").lower()
    if kind == "local":
        repo = os.environ.get("SMP_LOCAL_REPO") or "."
        try:
            return LocalGitProvider(repo)
        except FileNotFoundError:
            log.warning("git_provider_local_unavailable", repo=repo)
            return NullGitProvider()
    if kind == "github":
        repo = os.environ.get("SMP_GITHUB_REPO", "")
        token = os.environ.get("SMP_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
        if not repo or not token:
            log.warning("git_provider_github_unconfigured", has_repo=bool(repo), has_token=bool(token))
            return NullGitProvider()
        return GitHubProvider(repo=repo, token=token)
    return NullGitProvider()


def get_provider(ctx: dict[str, Any]) -> GitProvider:
    """Return the per-server provider, lazily built from env."""
    provider = ctx.get("_git_provider")
    if isinstance(provider, GitProvider):
        return provider
    provider = provider_from_env()
    ctx["_git_provider"] = provider
    return provider


__all__ = [
    "GitHubProvider",
    "GitProvider",
    "LocalGitProvider",
    "NullGitProvider",
    "PullRequestRecord",
    "get_provider",
    "provider_from_env",
]
