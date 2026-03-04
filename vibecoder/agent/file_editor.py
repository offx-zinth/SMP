from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile


@dataclass(frozen=True)
class SearchReplaceBlock:
    search: str
    replace: str


class SearchReplaceParserError(ValueError):
    pass


class FileEditApplyError(RuntimeError):
    pass


class AiderStyleEditor:
    _LEFT = "<" * 7
    _RIGHT = ">" * 7
    _MID = "=" * 7
    SEARCH_MARKER = f"{_LEFT} SEARCH"
    SPLIT_MARKER = _MID
    REPLACE_MARKER = f"{_RIGHT} REPLACE"

    def parse_blocks(self, response_text: str) -> list[SearchReplaceBlock]:
        normalized_text = self._normalize_response_text(response_text)
        lines = normalized_text.splitlines(keepends=True)
        idx = 0
        blocks: list[SearchReplaceBlock] = []

        while idx < len(lines):
            line = lines[idx].strip("\n")
            if line.strip() != self.SEARCH_MARKER:
                idx += 1
                continue

            idx += 1
            search_lines: list[str] = []
            while idx < len(lines) and lines[idx].strip("\n").strip() != self.SPLIT_MARKER:
                search_lines.append(lines[idx])
                idx += 1

            if idx >= len(lines):
                raise SearchReplaceParserError("Malformed SEARCH/REPLACE block: missing splitter")

            idx += 1
            replace_lines: list[str] = []
            while idx < len(lines) and lines[idx].strip("\n").strip() != self.REPLACE_MARKER:
                replace_lines.append(lines[idx])
                idx += 1

            if idx >= len(lines):
                raise SearchReplaceParserError("Malformed SEARCH/REPLACE block: missing REPLACE marker")

            idx += 1
            blocks.append(SearchReplaceBlock(search="".join(search_lines), replace="".join(replace_lines)))

        if not blocks:
            raise SearchReplaceParserError("No SEARCH/REPLACE blocks found in model output.")
        return blocks

    def apply_blocks(self, file_path: str | Path, blocks: list[SearchReplaceBlock]) -> str:
        path = Path(file_path)
        original = path.read_text(encoding="utf-8")
        updated = original

        for block in blocks:
            search = block.search
            replace = block.replace

            if not search:
                raise FileEditApplyError("SEARCH section cannot be empty for safe edit application.")

            match_count = updated.count(search)
            if match_count == 0:
                raise FileEditApplyError("SEARCH block not found in file; aborting edit for safety.")
            if match_count > 1:
                raise FileEditApplyError("SEARCH block is ambiguous (multiple matches); aborting edit.")

            updated = updated.replace(search, replace, 1)

        if updated != original:
            self._atomic_write(path, updated)

        return updated

    def apply_response(self, file_path: str | Path, response_text: str) -> str:
        blocks = self.parse_blocks(response_text)
        return self.apply_blocks(file_path, blocks)

    def _normalize_response_text(self, response_text: str) -> str:
        """Strip conversational wrappers, markdown fences, and trailing filler around edit blocks."""
        start_idx = response_text.find(self.SEARCH_MARKER)
        if start_idx == -1:
            return response_text

        end_idx = response_text.rfind(self.REPLACE_MARKER)
        if end_idx == -1:
            trimmed = response_text[start_idx:]
        else:
            trimmed = response_text[start_idx : end_idx + len(self.REPLACE_MARKER)]

        normalized_lines: list[str] = []
        for line in trimmed.splitlines(keepends=True):
            if line.strip().startswith("```"):
                continue
            normalized_lines.append(line)
        return "".join(normalized_lines)

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            handle.write(content)
            temp_name = handle.name
        Path(temp_name).replace(path)
