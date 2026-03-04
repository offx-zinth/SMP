from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
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
    SEARCH_MARKER = "<<<<<<< SEARCH"
    SPLIT_MARKER = "======="
    REPLACE_MARKER = ">>>>>>> REPLACE"

    _FENCE_LINE_RE = re.compile(r"^`{3,}[^`]*$|^~{3,}[^~]*$")

    def parse_blocks(self, response_text: str) -> list[SearchReplaceBlock]:
        lines = self._trim_to_blocks(response_text).splitlines(keepends=True)
        idx = 0
        blocks: list[SearchReplaceBlock] = []

        while idx < len(lines):
            line = lines[idx]
            if not self._is_marker_line(line, self.SEARCH_MARKER):
                idx += 1
                continue

            idx += 1
            search_lines: list[str] = []
            while idx < len(lines) and not self._is_marker_line(lines[idx], self.SPLIT_MARKER):
                search_lines.append(lines[idx])
                idx += 1

            if idx >= len(lines):
                raise SearchReplaceParserError("Malformed SEARCH/REPLACE block: missing splitter")

            idx += 1
            replace_lines: list[str] = []
            while idx < len(lines) and not self._is_marker_line(lines[idx], self.REPLACE_MARKER):
                replace_lines.append(lines[idx])
                idx += 1

            if idx >= len(lines):
                raise SearchReplaceParserError("Malformed SEARCH/REPLACE block: missing REPLACE marker")

            idx += 1
            blocks.append(
                SearchReplaceBlock(
                    search=self._strip_wrapping_markdown("".join(search_lines)),
                    replace=self._strip_wrapping_markdown("".join(replace_lines)),
                )
            )

        if not blocks:
            raise SearchReplaceParserError("No SEARCH/REPLACE blocks found in model output.")
        return blocks

    def _trim_to_blocks(self, response_text: str) -> str:
        lines = response_text.splitlines(keepends=True)
        first_search: int | None = None
        last_replace: int | None = None

        for i, line in enumerate(lines):
            if first_search is None and self._is_marker_line(line, self.SEARCH_MARKER):
                first_search = i
            if self._is_marker_line(line, self.REPLACE_MARKER):
                last_replace = i

        if first_search is None or last_replace is None or first_search > last_replace:
            return response_text
        return "".join(lines[first_search : last_replace + 1])

    def _is_marker_line(self, raw_line: str, marker: str) -> bool:
        line = raw_line.strip()
        if not line:
            return False
        line = line.strip("`").strip()
        return line == marker

    def _strip_wrapping_markdown(self, content: str) -> str:
        lines = content.splitlines(keepends=True)
        if not lines:
            return content

        start = 0
        end = len(lines)
        while start < end and not lines[start].strip():
            start += 1
        while end > start and not lines[end - 1].strip():
            end -= 1

        trimmed = lines[start:end]
        if len(trimmed) >= 2:
            first = trimmed[0].strip()
            last = trimmed[-1].strip()
            if self._FENCE_LINE_RE.match(first) and self._FENCE_LINE_RE.match(last):
                trimmed = trimmed[1:-1]

        return "".join(trimmed)

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

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            handle.write(content)
            temp_name = handle.name
        Path(temp_name).replace(path)
