from __future__ import annotations

from pathlib import Path

from git import InvalidGitRepositoryError, Repo
from google import genai

from vibecoder.context import AppContext


class GitManager:
    """Git safety wrapper used by the orchestrator and REPL commands."""

    def __init__(self, app_context: AppContext) -> None:
        self.context = app_context
        self.workspace = app_context.config.workspace_dir.resolve()
        self._repo = self._load_repo()
        self._genai_client = genai.Client(api_key=app_context.config.gemini_api_key)

    def _load_repo(self) -> Repo | None:
        try:
            return Repo(self.workspace, search_parent_directories=True)
        except InvalidGitRepositoryError:
            return None

    def is_repo(self) -> bool:
        return self._repo is not None

    def commit_changes(self, files: list[str], diff_summary: str) -> str:
        if not self._repo:
            raise RuntimeError("Workspace is not a git repository.")
        if not files:
            return "No files to commit."

        repo = self._repo
        worktree = Path(repo.working_tree_dir or self.workspace).resolve()
        relative_files: list[str] = []
        for file in files:
            path = Path(file).resolve()
            if worktree not in path.parents and path != worktree:
                continue
            relative_files.append(str(path.relative_to(worktree)))

        if not relative_files:
            return "No repository-scoped files to commit."

        repo.index.add(relative_files)
        if not repo.is_dirty(index=True, working_tree=False, untracked_files=False):
            return "No staged changes to commit."

        message = self._generate_commit_message(diff_summary)
        commit = repo.index.commit(message)
        return f"Committed {len(relative_files)} file(s): {commit.hexsha[:8]} — {message}"

    def undo_last_commit(self) -> str:
        if not self._repo:
            return "Cannot undo: workspace is not a git repository."
        repo = self._repo
        if not repo.head.is_valid():
            return "Cannot undo: repository has no commits."
        repo.git.reset("--hard", "HEAD~1")
        return "Undid last commit with hard reset (HEAD~1)."

    def _generate_commit_message(self, diff_summary: str) -> str:
        prompt = (
            "Write a concise Conventional Commit message. "
            "Max 72 chars. Single line only.\n\n"
            f"Diff summary:\n{diff_summary[:6000]}"
        )
        response = self._genai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        first_line = ((response.text or "").strip().splitlines() or [""])[0].strip()
        return first_line or "chore: apply vibecoder changes"
