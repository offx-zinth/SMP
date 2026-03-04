from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from git import InvalidGitRepositoryError, Repo
from google import genai


class GitSafetyManager:
    def __init__(self, workspace: str | Path = ".") -> None:
        self.workspace = Path(workspace).resolve()
        self._repo = self._load_repo()
        self._genai_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    def _load_repo(self) -> Repo | None:
        try:
            return Repo(self.workspace, search_parent_directories=True)
        except InvalidGitRepositoryError:
            return None

    @property
    def is_repo(self) -> bool:
        return self._repo is not None

    def commit_edits(self, files_changed: list[str], message: str | None = None) -> str:
        if not self._repo:
            return "Skipped commit: workspace is not a git repository."
        if not files_changed:
            return "Skipped commit: no files changed."

        repo = self._repo
        relative_files = [str(Path(path).resolve().relative_to(Path(repo.working_tree_dir).resolve())) for path in files_changed]
        repo.index.add(relative_files)

        if not repo.is_dirty(index=True, working_tree=True, untracked_files=True):
            return "Skipped commit: index has no changes."

        commit_message = message.strip() if message else self._generate_commit_message(relative_files)
        commit = repo.index.commit(commit_message)
        return f"Committed {len(relative_files)} file(s): {commit.hexsha[:8]}"

    def undo_last_commit(self) -> str:
        if not self._repo:
            return "Cannot undo: workspace is not a git repository."
        repo = self._repo
        if not repo.head.is_valid():
            return "Cannot undo: repository has no commits."

        repo.git.reset("--soft", "HEAD~1")
        return "Reverted last commit (soft reset to HEAD~1)."

    def _generate_commit_message(self, files_changed: Iterable[str]) -> str:
        if not self._repo:
            return "chore: apply vibecoder edits"

        diff = self._repo.git.diff("--cached", "--", *files_changed)
        if not diff.strip():
            return "chore: apply vibecoder edits"

        prompt = (
            "Write a concise Conventional Commit message for this diff. "
            "Return one line only, max 72 chars.\n\n"
            f"Diff:\n{diff[:12000]}"
        )
        response = self._genai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        text = (response.text or "").strip().splitlines()[0:1]
        candidate = text[0].strip() if text else ""
        return candidate or "chore: apply vibecoder edits"
