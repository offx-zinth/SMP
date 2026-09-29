"""BM25 ranking for keyword search over graph nodes.

Implements the classic Okapi BM25 with field-weighted term frequencies,
document-length normalisation, and IDF — the piece SMP lacked versus
``codebase-memory-mcp`` (which uses BM25 + pagination).

Field weights mirror codebase-memory priorities: names matter most,
then tags/ids, then docstrings/descriptions, then file paths/signatures.
"""

from __future__ import annotations

import math
import re
from typing import Any

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")

K1 = 1.2
B = 0.75

FIELD_WEIGHTS: dict[str, float] = {
    "name": 5.0,
    "id": 2.0,
    "tags": 3.0,
    "docstring": 2.0,
    "description": 1.5,
    "decorators": 1.5,
    "file_path": 1.0,
    "signature": 1.0,
}


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokeniser shared by queries and documents."""
    if not text:
        return []
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text.lower()):
        # Split snake_case / camelCase into sub-tokens plus the whole token.
        parts = raw.split("_")
        for part in parts:
            if part:
                tokens.append(part)
                # Camel-case split: "upsertNode" -> "upsert", "node".
                camel = re.findall(r"[a-z]+|[A-Z][a-z]*|[0-9]+", part)
                if len(camel) > 1:
                    tokens.extend(t.lower() for t in camel if t)
        if "_" not in raw:
            # Already added as `part`; avoid double count for simple tokens.
            pass
        else:
            tokens.append(raw)
    return tokens


def tokenize_query(query: str) -> list[str]:
    """Tokenise a raw query string into BM25 terms."""
    return [t for t in tokenize(query) if len(t) >= 2 or t.isdigit()]


def _field_tokens(node: Any) -> dict[str, list[str]]:
    """Extract per-field token lists from a GraphNode (duck-typed)."""
    name = getattr(getattr(node, "structural", None), "name", "") or ""
    signature = getattr(getattr(node, "structural", None), "signature", "") or ""
    semantic = getattr(node, "semantic", None)
    docstring = getattr(semantic, "docstring", "") or ""
    description = getattr(semantic, "description", "") or ""
    tags = getattr(semantic, "tags", []) or []
    decorators = getattr(semantic, "decorators", []) or []
    node_id = getattr(node, "id", "") or ""
    file_path = getattr(node, "file_path", "") or ""
    return {
        "name": tokenize(name),
        "id": tokenize(node_id.replace("::", " ")),
        "tags": tokenize(" ".join(tags)),
        "docstring": tokenize(docstring),
        "description": tokenize(description),
        "decorators": tokenize(" ".join(decorators)),
        "file_path": tokenize(file_path.replace("/", " ").replace(".", " ")),
        "signature": tokenize(signature),
    }


def build_corpus(nodes: list[Any]) -> tuple[list[dict[str, list[str]]], dict[str, float], float]:
    """Pre-compute per-doc field tokens, IDF map, and average doc length.

    Returns ``(doc_fields, idf, avgdl)`` where doc length is the
    weight-adjusted token count used for BM25 length normalisation.
    """
    doc_fields = [_field_tokens(n) for n in nodes]
    doc_count = max(1, len(nodes))
    doc_freq: dict[str, int] = {}
    lengths: list[float] = []
    for fields in doc_fields:
        seen: set[str] = set()
        length = 0.0
        for field, toks in fields.items():
            weight = FIELD_WEIGHTS.get(field, 1.0)
            length += len(toks) * weight
            seen.update(toks)
        lengths.append(length)
        for term in seen:
            doc_freq[term] = doc_freq.get(term, 0) + 1
    idf = {t: math.log((doc_count - df + 0.5) / (df + 0.5) + 1.0) for t, df in doc_freq.items()}
    avgdl = sum(lengths) / max(1, len(lengths)) or 1.0
    return doc_fields, idf, avgdl


def score_node(
    query_terms: list[str],
    fields: dict[str, list[str]],
    idf: dict[str, float],
    avgdl: float,
    doc_length: float | None = None,
) -> tuple[float, str]:
    """Score one document; returns ``(score, matched_on)``."""
    if doc_length is None:
        doc_length = sum(len(toks) * FIELD_WEIGHTS.get(f, 1.0) for f, toks in fields.items()) or 1.0
    score = 0.0
    matched_fields: list[str] = []
    for term in query_terms:
        term_idf = idf.get(term, 0.0)
        if term_idf <= 0:
            continue
        for field, toks in fields.items():
            tf = sum(1 for t in toks if t == term or term in t)
            if tf <= 0:
                continue
            weight = FIELD_WEIGHTS.get(field, 1.0)
            norm_tf = (tf * (K1 + 1.0)) / (tf + K1 * (1.0 - B + B * (doc_length / avgdl)))
            score += term_idf * norm_tf * weight
            if field not in matched_fields:
                matched_fields.append(field)
    # Exact-name boost: full query equals the entity name.
    name_text = " ".join(fields.get("name", []))
    if query_terms and " ".join(query_terms) == name_text:
        score += 100.0
    matched_on = ", ".join(matched_fields[:3]) if matched_fields else ""
    return score, matched_on


def rank(
    query: str,
    nodes: list[Any],
    *,
    top_k: int = 10,
    offset: int = 0,
    match: str = "any",
) -> list[tuple[float, str, Any]]:
    """Rank *nodes* for *query*; returns ``(score, matched_on, node)`` triples.

    ``match="all"`` requires every query term to appear in at least one
    field; ``"any"`` (default) requires at least one term.
    """
    terms = tokenize_query(query)
    if not terms:
        # Fall back to raw split for single-char queries.
        terms = [t.lower() for t in query.split() if t]
    if not terms:
        return []
    doc_fields, idf, avgdl = build_corpus(nodes)
    scored: list[tuple[float, str, object]] = []
    for node, fields in zip(nodes, doc_fields, strict=True):
        hay = set()
        for toks in fields.values():
            hay.update(toks)
            # Substring matching: "upsert" matches "upsert_node".
            for tok in toks:
                hay.add(tok)
        present = [t for t in terms if t in hay or any(t in h for h in hay)]
        if match == "all" and len(present) < len(terms):
            continue
        if not present:
            continue
        length = sum(len(toks) * FIELD_WEIGHTS.get(f, 1.0) for f, toks in fields.items()) or 1.0
        score, matched_on = score_node(terms, fields, idf, avgdl, length)
        # Phrase bonus when the raw query is a substring of name/id/path.
        raw = query.lower()
        name_exact = getattr(getattr(node, "structural", None), "name", "").lower()
        if raw and (raw == name_exact or raw in getattr(node, "id", "").lower()):
            score += 20.0
        if score > 0:
            scored.append((score, matched_on or "name", node))
    scored.sort(key=lambda x: -x[0])
    return scored[offset : offset + top_k] if top_k > 0 else scored[offset:]


def count_matches(query: str, nodes: list[Any], *, match: str = "any") -> int:
    """Count matches without slicing (for pagination totals)."""
    return len(rank(query, nodes, top_k=0, offset=0, match=match))
