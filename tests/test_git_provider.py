"""Phase 5 tests: pluggable Git provider for ``smp/pr/create``."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from smp.runtime.git_provider import (
    GitHubProvider,
    LocalGitProvider,
    NullGitProvider,
    provider_from_env,
)


# ---------------------------------------------------------------------------
# Null provider
# ---------------------------------------------------------------------------


class TestNullProvider:
    async def test_returns_synthetic_record(self) -> None:
        provider = NullGitProvider()
        record = await provider.create_pull_request(
            title="t", body="b", branch="feature/x", base_branch="main"
        )
        assert record.provider == "null"
        assert record.pr_id.startswith("pr_")
        assert record.url.startswith("smp://null/")
        assert record.branch == "feature/x"


# ---------------------------------------------------------------------------
# Local provider — uses real ``git``
# ---------------------------------------------------------------------------


def _git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    return True


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    if not _git_available():
        pytest.skip("git binary not available")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "main"], cwd=repo, check=True)
    (repo / "README.md").write_text("# initial\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


class TestLocalProvider:
    async def test_creates_branch_and_commits(self, git_repo: Path) -> None:
        provider = LocalGitProvider(git_repo)
        record = await provider.create_pull_request(
            title="add greeting",
            body="adds hello.txt",
            branch="feature/hello",
            base_branch="main",
            files={"hello.txt": "hi\n"},
        )
        assert record.provider == "local"
        assert record.branch == "feature/hello"
        assert (git_repo / "hello.txt").exists()

        # Branch exists with the new file
        result = subprocess.run(
            ["git", "log", "-1", "--name-only", "--pretty=format:", "feature/hello"],
            cwd=git_repo, capture_output=True, text=True, check=True
        )
        assert "hello.txt" in result.stdout

    async def test_no_files_means_no_commit(self, git_repo: Path) -> None:
        provider = LocalGitProvider(git_repo)
        before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=git_repo, capture_output=True, text=True, check=True).stdout.strip()
        record = await provider.create_pull_request(
            title="empty", body="", branch="feature/empty", base_branch="main", files={}
        )
        after = subprocess.run(
            ["git", "rev-parse", "feature/empty"], cwd=git_repo, capture_output=True, text=True, check=True
        ).stdout.strip()
        assert before == after  # no new commit
        assert record.branch == "feature/empty"

    async def test_rejects_path_escape(self, git_repo: Path) -> None:
        provider = LocalGitProvider(git_repo)
        with pytest.raises(ValueError, match="escapes repository"):
            await provider.create_pull_request(
                title="bad", body="", branch="feature/bad", base_branch="main",
                files={"../escape.txt": "no"},
            )

    async def test_constructor_rejects_non_repo(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="not a git repo"):
            LocalGitProvider(tmp_path)


# ---------------------------------------------------------------------------
# GitHub provider — verified with a fake HTTP opener
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload


class _FakeOpener:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.last_request: Any = None

    def open(self, request: Any, timeout: float = 0) -> _FakeResponse:
        del timeout
        self.last_request = request
        return _FakeResponse(self.response)


class TestGitHubProvider:
    async def test_creates_pull_request_via_api(self) -> None:
        opener = _FakeOpener(
            {"number": 42, "html_url": "https://github.com/o/r/pull/42", "created_at": "2025-04-25T00:00:00Z"}
        )
        provider = GitHubProvider(repo="o/r", token="ghs_test", opener=opener)
        record = await provider.create_pull_request(
            title="feat", body="body", branch="feature/x", base_branch="main"
        )
        assert record.provider == "github"
        assert record.number == 42
        assert record.url == "https://github.com/o/r/pull/42"
        assert record.pr_id == "gh_42"

        sent = opener.last_request
        assert sent.full_url.endswith("/repos/o/r/pulls")
        assert sent.headers["Authorization"] == "Bearer ghs_test"

    def test_constructor_validates_repo_format(self) -> None:
        with pytest.raises(ValueError, match="owner/name"):
            GitHubProvider(repo="badformat", token="ghs_test")


# ---------------------------------------------------------------------------
# Environment-driven selection
# ---------------------------------------------------------------------------


class TestProviderFromEnv:
    def test_default_is_null(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SMP_GIT_PROVIDER", raising=False)
        provider = provider_from_env()
        assert isinstance(provider, NullGitProvider)

    def test_local_provider_resolves(self, git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SMP_GIT_PROVIDER", "local")
        monkeypatch.setenv("SMP_LOCAL_REPO", str(git_repo))
        provider = provider_from_env()
        assert isinstance(provider, LocalGitProvider)

    def test_local_falls_back_when_repo_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SMP_GIT_PROVIDER", "local")
        monkeypatch.setenv("SMP_LOCAL_REPO", str(tmp_path / "absent"))
        provider = provider_from_env()
        assert isinstance(provider, NullGitProvider)

    def test_github_requires_repo_and_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SMP_GIT_PROVIDER", "github")
        monkeypatch.delenv("SMP_GITHUB_REPO", raising=False)
        monkeypatch.delenv("SMP_GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        provider = provider_from_env()
        assert isinstance(provider, NullGitProvider)


# ---------------------------------------------------------------------------
# pr/create end-to-end via the handler
# ---------------------------------------------------------------------------


class TestPrCreateHandler:
    async def test_pr_create_returns_provider_metadata(self, git_repo: Path) -> None:
        from smp.engine.graph_builder import DefaultGraphBuilder
        from smp.engine.query import DefaultQueryEngine
        from smp.protocol.handlers.review import pr_create
        from smp.store.graph.mmap_store import MMapGraphStore

        store_path = git_repo.parent / "graph.smpg"
        store = MMapGraphStore(store_path)
        await store.connect()
        try:
            ctx: dict[str, Any] = {
                "graph": store,
                "engine": DefaultQueryEngine(graph_store=store),
                "builder": DefaultGraphBuilder(store),
                "_git_provider": LocalGitProvider(git_repo),
            }
            result = await pr_create(
                {
                    "title": "feat",
                    "body": "body",
                    "branch": "feature/handler",
                    "base_branch": "main",
                },
                ctx,
            )
            assert result["created"] is True
            assert result["provider"] == "local"
            assert result["pr_id"].startswith("pr_")
            assert result["branch"] == "feature/handler"
            assert "url" in result
        finally:
            await store.close()

    async def test_pr_create_handles_provider_error(self, tmp_path: Path) -> None:
        from smp.engine.graph_builder import DefaultGraphBuilder
        from smp.engine.query import DefaultQueryEngine
        from smp.protocol.handlers.review import pr_create
        from smp.runtime.git_provider import GitProvider
        from smp.store.graph.mmap_store import MMapGraphStore

        class BoomProvider(GitProvider):
            name = "boom"

            async def create_pull_request(self, **_: Any) -> Any:
                raise RuntimeError("network down")

        store_path = tmp_path / "graph.smpg"
        store = MMapGraphStore(store_path)
        await store.connect()
        try:
            ctx: dict[str, Any] = {
                "graph": store,
                "engine": DefaultQueryEngine(graph_store=store),
                "builder": DefaultGraphBuilder(store),
                "_git_provider": BoomProvider(),
            }
            result = await pr_create(
                {"title": "t", "body": "", "branch": "x", "base_branch": "main"}, ctx
            )
            assert result["created"] is False
            assert result["error"] == "git_provider_error"
            assert "network down" in result["detail"]
        finally:
            await store.close()
