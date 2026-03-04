from __future__ import annotations

from dataclasses import dataclass
import difflib
import re
from typing import Iterable


SEARCH_MARKER = "<<<<<<< SEARCH"
SPLIT_MARKER = "======="
REPLACE_MARKER = ">>>>>>> REPLACE"

_COMMENT_RE = re.compile(r"^\s*(#|//|/\*|\*|\*/)")
_FENCE_RE = re.compile(r"^(```|~~~)")


class EditFailedException(RuntimeError):
    """Raised when a fuzzy edit cannot be applied safely."""


class AmbiguousMatchError(EditFailedException):
    """Raised when multiple fuzzy windows are equally valid for the SEARCH block."""

    def __init__(self, line_numbers: list[int], score: float) -> None:
        self.line_numbers = line_numbers
        self.score = score
        super().__init__(
            "Ambiguous SEARCH match. Potential matches start on lines "
            f"{line_numbers} with score={score:.1%}. Expand SEARCH with unique surrounding lines."
        )


@dataclass(frozen=True, slots=True)
class SearchReplaceBlock:
    search: str
    replace: str


@dataclass(frozen=True, slots=True)
class _MatchResult:
    score: float
    start: int
    end: int
    rationale: str


def parse_search_replace_blocks(text: str) -> list[SearchReplaceBlock]:
    """Parse Aider-style SEARCH/REPLACE blocks from model output."""
    lines = text.splitlines(keepends=True)
    blocks: list[SearchReplaceBlock] = []
    idx = 0

    while idx < len(lines):
        if not _is_marker(lines[idx], SEARCH_MARKER):
            idx += 1
            continue

        idx += 1
        search_lines: list[str] = []
        while idx < len(lines) and not _is_marker(lines[idx], SPLIT_MARKER):
            search_lines.append(lines[idx])
            idx += 1
        if idx >= len(lines):
            raise EditFailedException("Malformed SEARCH/REPLACE block: missing ======= marker.")

        idx += 1
        replace_lines: list[str] = []
        while idx < len(lines) and not _is_marker(lines[idx], REPLACE_MARKER):
            replace_lines.append(lines[idx])
            idx += 1
        if idx >= len(lines):
            raise EditFailedException("Malformed SEARCH/REPLACE block: missing >>>>>>> REPLACE marker.")

        idx += 1
        blocks.append(
            SearchReplaceBlock(
                search=_strip_fence("".join(search_lines)),
                replace=_strip_fence("".join(replace_lines)),
            )
        )

    if not blocks:
        raise EditFailedException("No SEARCH/REPLACE blocks were found in model output.")
    return blocks


def apply_edit_fuzzy(original_text: str, search_block: str, replace_block: str, *, threshold: float = 0.90) -> str:
    """Apply one fuzzy SEARCH/REPLACE block to text using line-aware matching."""
    if not search_block.strip():
        raise EditFailedException("SEARCH block is empty; refusing unsafe edit.")

    original_lines = original_text.splitlines(keepends=True)
    search_lines = search_block.splitlines(keepends=True)

    if not original_lines:
        raise EditFailedException("Target file is empty; SEARCH block cannot be matched.")

    best, ties = _find_best_match(original_lines, search_lines)
    if best.score < threshold:
        raise EditFailedException(
            "Fuzzy match confidence below threshold. "
            f"required={threshold:.0%}, actual={best.score:.1%}, window=lines[{best.start}:{best.end}]. "
            f"details={best.rationale}. "
            "Tip: include more unique unchanged lines in SEARCH and avoid paraphrasing code."
        )

    if len(ties) > 1:
        raise AmbiguousMatchError(line_numbers=[match.start + 1 for match in ties], score=best.score)

    updated_lines = original_lines[: best.start] + replace_block.splitlines(keepends=True) + original_lines[best.end :]
    return "".join(updated_lines)


def _find_best_match(original_lines: list[str], search_lines: list[str]) -> tuple[_MatchResult, list[_MatchResult]]:
    base_len = max(1, len(search_lines))
    min_len = max(1, base_len - 1)
    max_len = min(len(original_lines), base_len + 6)

    informative = [line for line in search_lines if _is_informative(line)]
    best = _MatchResult(score=0.0, start=0, end=min_len, rationale="no candidate evaluated")
    epsilon = 0.005
    ties: list[_MatchResult] = []

    for win_len in range(min_len, max_len + 1):
        limit = len(original_lines) - win_len + 1
        for start in range(max(0, limit)):
            end = start + win_len
            window = original_lines[start:end]
            score, rationale = _score_window(search_lines, window, informative_count=len(informative))
            candidate = _MatchResult(score=score, start=start, end=end, rationale=rationale)
            if score > best.score + epsilon:
                best = candidate
                ties = [candidate]
            elif abs(score - best.score) <= epsilon:
                ties.append(candidate)

    unique_ties: list[_MatchResult] = []
    seen: set[tuple[int, int]] = set()
    for tie in ties:
        key = (tie.start, tie.end)
        if key not in seen:
            unique_ties.append(tie)
            seen.add(key)
    return best, unique_ties


def _score_window(search: Iterable[str], window: Iterable[str], *, informative_count: int) -> tuple[float, str]:
    search_lines = list(search)
    window_lines = list(window)

    s_norm = [_normalize(line) for line in search_lines]
    w_norm = [_normalize(line) for line in window_lines]

    s_filtered = [_normalize(line) for line in search_lines if _is_informative(line)]
    w_filtered = [_normalize(line) for line in window_lines if _is_informative(line)]
    pair_count = min(len(s_filtered), len(w_filtered))

    if pair_count:
        line_score = sum(
            difflib.SequenceMatcher(None, s_filtered[idx], w_filtered[idx]).ratio()
            for idx in range(pair_count)
        ) / pair_count
    else:
        line_score = difflib.SequenceMatcher(None, s_norm, w_norm).ratio()

    if not s_filtered:
        seq_score = difflib.SequenceMatcher(None, s_norm, w_norm).ratio()
    else:
        seq_score = difflib.SequenceMatcher(None, "\n".join(s_filtered), "\n".join(w_filtered)).ratio()

    length_penalty = 1.0 - min(0.2, abs(len(search_lines) - len(window_lines)) * 0.03)
    info_bonus = 0.05 if informative_count and s_filtered[:2] == w_filtered[:2] else 0.0

    coverage = pair_count / max(1, len(search_lines))
    score = min(1.0, ((line_score * 0.5) + (seq_score * 0.4) + (coverage * 0.1) + info_bonus) * length_penalty)
    rationale = (
        f"line_score={line_score:.1%}, seq_score={seq_score:.1%}, "
        f"len(search)={len(search_lines)}, len(window)={len(window_lines)}"
    )
    return score, rationale


def _is_informative(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return _COMMENT_RE.match(stripped) is None


def _normalize(line: str) -> str:
    return " ".join(line.strip().split())


def _is_marker(line: str, marker: str) -> bool:
    return line.strip().strip("`") == marker


def _strip_fence(text: str) -> str:
    lines = text.splitlines(keepends=True)
    if len(lines) >= 2 and _FENCE_RE.match(lines[0].strip()) and _FENCE_RE.match(lines[-1].strip()):
        return "".join(lines[1:-1])
    return text
