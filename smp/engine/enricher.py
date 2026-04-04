"""Semantic enricher — structural analysis + Gemini LLM enrichment.

Two-tier approach:
  Tier 1 (default): Static analysis generates purpose from code structure.
  Tier 2 (when GEMINI_API_KEY is set): Uses Google Gemini for rich summaries
    and high-quality embeddings.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Any

from smp.core.models import GraphNode, NodeType, SemanticInfo
from smp.engine.interfaces import SemanticEnricher as SemanticEnricherInterface
from smp.logging import get_logger

log = get_logger(__name__)

# Embedding dimensionality (matches Gemini text-embedding-004 default)
_EMBED_DIM = 768


# ---------------------------------------------------------------------------
# Static analysis — always available, no API keys
# ---------------------------------------------------------------------------

def _static_purpose(node: GraphNode) -> tuple[str, float]:
    """Generate a purpose string from structural analysis.

    Returns (purpose, confidence). Confidence ranges 0.0–0.6.
    """
    # 1. Docstring is the best signal
    if node.docstring:
        # Clean up multi-line docstrings
        doc = " ".join(node.docstring.split())
        if len(doc) > 200:
            doc = doc[:197] + "..."
        return doc, 0.6

    name = node.name
    sig = node.signature
    node_type = node.type

    # 2. Infer from name patterns
    purpose = _infer_from_name(name, node_type, sig, node.metadata)

    # 3. Boost confidence if we have a signature
    confidence = 0.3 if sig else 0.2

    return purpose, confidence


def _infer_from_name(
    name: str,
    node_type: NodeType,
    sig: str,
    metadata: dict[str, str],
) -> str:
    """Infer purpose from the node name and type."""
    # Snake/camel case to words
    words = _split_name(name)

    if node_type == NodeType.IMPORT:
        return f"Imports {name}"

    if node_type == NodeType.CLASS:
        kind = metadata.get("kind", "class")
        decorators = metadata.get("decorators", "")
        if "dataclass" in decorators:
            return f"Data class {name}"
        if kind == "interface":
            return f"Interface defining {name} contract"
        return f"Class {name}"

    if node_type in (NodeType.FUNCTION, NodeType.METHOD):
        class_ctx = metadata.get("class", "")
        decorators = metadata.get("decorators", "")
        prefix = f"Method of {class_ctx}" if class_ctx else "Function"

        # Common patterns
        if name.startswith("__") and name.endswith("__"):
            dunder_map = {
                "__init__": f"Initialiser for {class_ctx}" if class_ctx else "Constructor",
                "__str__": f"String representation of {class_ctx}",
                "__repr__": f"Debug representation of {class_ctx}",
                "__eq__": f"Equality comparison for {class_ctx}",
                "__hash__": f"Hash computation for {class_ctx}",
                "__enter__": f"Context manager entry for {class_ctx}",
                "__exit__": f"Context manager exit for {class_ctx}",
                "__aenter__": f"Async context manager entry for {class_ctx}",
                "__aexit__": f"Async context manager exit for {class_ctx}",
                "__len__": f"Length of {class_ctx}",
                "__getitem__": f"Index access for {class_ctx}",
                "__setitem__": f"Index assignment for {class_ctx}",
                "__iter__": f"Iterator for {class_ctx}",
                "__next__": f"Next item from {class_ctx}",
            }
            return dunder_map.get(name, f"Dunder method {name}")

        # Verb-based inference
        first_word = words[0].lower() if words else ""
        verb_map = {
            "get": "Retrieves",
            "set": "Sets",
            "create": "Creates",
            "make": "Creates",
            "build": "Builds",
            "delete": "Deletes",
            "remove": "Removes",
            "add": "Adds",
            "update": "Updates",
            "find": "Finds",
            "search": "Searches for",
            "parse": "Parses",
            "extract": "Extracts",
            "validate": "Validates",
            "check": "Checks",
            "is": "Checks if",
            "has": "Checks if has",
            "can": "Checks if can",
            "should": "Determines if should",
            "will": "Determines if will",
            "connect": "Connects to",
            "close": "Closes",
            "open": "Opens",
            "send": "Sends",
            "receive": "Receives",
            "handle": "Handles",
            "process": "Processes",
            "run": "Runs",
            "execute": "Executes",
            "start": "Starts",
            "stop": "Stops",
            "init": "Initialises",
            "setup": "Sets up",
            "tear": "Tears down",
            "convert": "Converts",
            "transform": "Transforms",
            "format": "Formats",
            "render": "Renders",
            "load": "Loads",
            "save": "Saves",
            "store": "Stores",
            "read": "Reads",
            "write": "Writes",
            "log": "Logs",
            "print": "Prints",
            "test": "Tests",
            "mock": "Mocks",
            "enforce": "Enforces",
            "ensure": "Ensures",
            "verify": "Verifies",
            "call": "Calls",
            "apply": "Applies",
            "traverse": "Traverses",
            "walk": "Walks through",
            "ingest": "Ingests",
            "embed": "Generates embedding for",
            "query": "Queries",
            "navigate": "Navigates",
            "trace": "Traces",
            "assess": "Assesses",
            "locate": "Locates",
            "clear": "Clears",
            "reset": "Resets",
        }
        action = verb_map.get(first_word, "Implements")
        detail = " ".join(words[1:]) if len(words) > 1 else name

        if "test" in decorators or name.startswith("test_"):
            return f"Test: {name.replace('_', ' ')}"

        return f"{prefix} {action} {detail}".replace("_", " ")

    if node_type == NodeType.FILE:
        return f"Source file {name}"

    return f"{node_type.value} {name}"


def _split_name(name: str) -> list[str]:
    """Split camelCase or snake_case name into words."""
    # Handle snake_case
    if "_" in name:
        return [w for w in name.split("_") if w]
    # Handle camelCase
    parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", name)
    return parts if parts else [name]


# ---------------------------------------------------------------------------
# Deterministic hash-based embedding (for development / testing)
# ---------------------------------------------------------------------------

def _hash_embed(text: str, dim: int = _EMBED_DIM) -> list[float]:
    """Generate a deterministic pseudo-embedding from text hash.

    Not semantically meaningful but reproducible and dimensionally correct.
    Useful for development and testing without API keys.
    """
    h = hashlib.sha256(text.encode("utf-8")).digest()
    rng = hashlib.md5(text.encode("utf-8")).digest()

    # Create a seed from both hashes
    seed_bytes = h + rng
    values: list[float] = []
    for i in range(dim):
        byte_idx = (i * 7 + 3) % len(seed_bytes)
        # Normalize to [-1, 1]
        val = (seed_bytes[byte_idx] / 127.5) - 1.0
        # Add variation based on position
        val += math.sin(i * 0.1) * 0.1
        values.append(val)

    # L2 normalise
    norm = math.sqrt(sum(v * v for v in values))
    if norm > 0:
        values = [v / norm for v in values]
    return values


# ---------------------------------------------------------------------------
# Gemini LLM enrichment (when API key is available)
# ---------------------------------------------------------------------------

class _GeminiBackend:
    """Wraps google.genai for LLM enrichment and embeddings."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        from google import genai
        self._client = genai.Client(api_key=api_key)
        self._model = model

    def generate_purpose(self, nodes: list[GraphNode]) -> list[tuple[str, float]]:
        """Generate purpose summaries for a batch of nodes."""
        if not nodes:
            return []

        # Build prompt
        parts: list[str] = []
        for i, n in enumerate(nodes):
            ctx = f"class={n.metadata.get('class', '')}" if n.metadata.get("class") else ""
            doc = f'docstring="{n.docstring}"' if n.docstring else ""
            parts.append(
                f"[{i}] {n.type.value} {n.name} ({n.signature}) {ctx} {doc}"
            )

        prompt = (
            "You are a code analysis assistant. For each code entity below, "
            "write exactly ONE concise sentence describing its purpose. "
            "Reply with ONLY a numbered list, one line per entity.\n\n"
            + "\n".join(parts)
        )

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
            )
            text = response.text or ""
            return self._parse_responses(text, len(nodes))
        except Exception as exc:
            log.warning("gemini_purpose_failed", error=str(exc))
            return [("", 0.0)] * len(nodes)

    def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""
        if not texts:
            return []

        try:
            from google.genai import types
            result = self._client.models.embed_content(
                model="text-embedding-004",
                contents=texts,
                config=types.EmbedContentConfig(output_dimensionality=_EMBED_DIM),
            )
            return [list(e.values) for e in result.embeddings]
        except Exception as exc:
            log.warning("gemini_embed_failed", error=str(exc))
            return [_hash_embed(t) for t in texts]

    @staticmethod
    def _parse_responses(text: str, expected: int) -> list[tuple[str, float]]:
        """Parse numbered list from LLM response."""
        results: list[tuple[str, float]] = []
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # Remove leading number/bullet
            match = re.match(r"^\d+[\.\)\]\:]\s*(.*)", line)
            if match:
                purpose = match.group(1).strip()
                if purpose:
                    results.append((purpose, 0.9))
            elif line.startswith("- "):
                results.append((line[2:].strip(), 0.9))

        # Pad if fewer results than expected
        while len(results) < expected:
            results.append(("", 0.0))
        return results[:expected]


# ---------------------------------------------------------------------------
# Main enricher class
# ---------------------------------------------------------------------------

class LLMSemanticEnricher(SemanticEnricherInterface):
    """Semantic enricher with static analysis + optional Gemini LLM.

    Without API key: uses static analysis (always works, confidence 0.2-0.6).
    With GEMINI_API_KEY env var or explicit api_key: uses Gemini for richer
    purpose summaries (confidence 0.9) and real embeddings.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-2.0-flash",
        embedding_dim: int = _EMBED_DIM,
        cache_max_size: int = 10_000,
    ) -> None:
        self._embedding_dim = embedding_dim
        self._gemini: _GeminiBackend | None = None
        self._cache: dict[str, SemanticInfo] = {}
        self._cache_order: list[str] = []
        self._cache_max = cache_max_size

        # Try to initialise Gemini
        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if key:
            try:
                self._gemini = _GeminiBackend(api_key=key, model=model)
                log.info("gemini_backend_active", model=model)
            except Exception as exc:
                log.warning("gemini_init_failed", error=str(exc), fallback="static")
        else:
            log.info("enricher_static_mode", reason="no_api_key")

    @property
    def has_llm(self) -> bool:
        return self._gemini is not None

    async def enrich_node(self, node: GraphNode) -> GraphNode:
        if node.semantic and node.semantic.purpose:
            return node

        # Check cache
        if node.id in self._cache:
            return self._with_semantic(node, self._cache[node.id])

        # Static purpose
        purpose, confidence = _static_purpose(node)

        # LLM upgrade (synchronous call wrapped for API compat)
        if self._gemini:
            try:
                results = self._gemini.generate_purpose([node])
                if results and results[0][0]:
                    purpose, confidence = results[0]
            except Exception as exc:
                log.debug("llm_enrich_failed", node_id=node.id, error=str(exc))

        # Generate embedding
        embed_text = f"{node.name}: {purpose}" if purpose else node.name
        if self._gemini:
            try:
                embeddings = self._gemini.generate_embeddings([embed_text])
                embedding = embeddings[0] if embeddings else _hash_embed(embed_text, self._embedding_dim)
            except Exception:
                embedding = _hash_embed(embed_text, self._embedding_dim)
        else:
            embedding = _hash_embed(embed_text, self._embedding_dim)

        sem = SemanticInfo(purpose=purpose, embedding=embedding, confidence=confidence)
        self._cache[node.id] = sem
        return self._with_semantic(node, sem)

    async def enrich_batch(self, nodes: list[GraphNode]) -> list[GraphNode]:
        # Filter to un-enriched
        to_enrich = [n for n in nodes if not (n.semantic and n.semantic.purpose)]
        if not to_enrich:
            return nodes

        # Static purposes first
        purposes: list[tuple[str, float]] = [_static_purpose(n) for n in to_enrich]

        # LLM upgrade for the batch
        if self._gemini:
            try:
                llm_results = self._gemini.generate_purpose(to_enrich)
                for i, (p, c) in enumerate(llm_results):
                    if p:
                        purposes[i] = (p, c)
            except Exception as exc:
                log.warning("batch_llm_failed", error=str(exc))

        # Generate embeddings in batch
        embed_texts = [
            f"{n.name}: {p}" if p else n.name
            for n, (p, _) in zip(to_enrich, purposes)
        ]
        if self._gemini:
            try:
                embeddings = self._gemini.generate_embeddings(embed_texts)
            except Exception:
                embeddings = [_hash_embed(t, self._embedding_dim) for t in embed_texts]
        else:
            embeddings = [_hash_embed(t, self._embedding_dim) for t in embed_texts]

        # Build enriched nodes
        enriched: list[GraphNode] = []
        idx = 0
        for node in nodes:
            if node.semantic and node.semantic.purpose:
                enriched.append(node)
            else:
                purpose, conf = purposes[idx]
                emb = embeddings[idx]
                sem = SemanticInfo(purpose=purpose, embedding=emb, confidence=conf)
                self._cache[node.id] = sem
                enriched.append(self._with_semantic(node, sem))
                idx += 1

        log.info("batch_enriched", total=len(nodes), enriched=len(to_enrich))
        return enriched

    async def embed(self, text: str) -> list[float]:
        if self._gemini:
            try:
                results = self._gemini.generate_embeddings([text])
                if results:
                    return results[0]
            except Exception:
                pass
        return _hash_embed(text, self._embedding_dim)

    def cache_put(self, node_id: str, sem: SemanticInfo) -> None:
        if node_id in self._cache:
            self._cache_order.remove(node_id)
        elif len(self._cache) >= self._cache_max:
            evict = self._cache_order.pop(0)
            del self._cache[evict]
        self._cache[node_id] = sem
        self._cache_order.append(node_id)

    def cache_get(self, node_id: str) -> SemanticInfo | None:
        if node_id in self._cache:
            self._cache_order.remove(node_id)
            self._cache_order.append(node_id)
        return self._cache.get(node_id)

    @staticmethod
    def _with_semantic(node: GraphNode, sem: SemanticInfo) -> GraphNode:
        return GraphNode(
            id=node.id,
            type=node.type,
            name=node.name,
            file_path=node.file_path,
            start_line=node.start_line,
            end_line=node.end_line,
            signature=node.signature,
            docstring=node.docstring,
            semantic=sem,
            metadata=node.metadata,
        )
