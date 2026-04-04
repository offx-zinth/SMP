"""Semantic enricher — supports both LLM enrichment and hash-only mode.

Set SMP_ENRICHMENT=none to disable LLM enrichment (no API calls, uses hash embeddings).
"""

from __future__ import annotations

import hashlib
import os
import re

import httpx

from smp.core.models import GraphNode, SemanticInfo
from smp.engine.interfaces import SemanticEnricher as SemanticEnricherInterface
from smp.logging import get_logger

log = get_logger(__name__)

_EMBED_DIM = 4096
_NVIDIA_EMBED_URL = "https://integrate.api.nvidia.com/v1/embeddings"


def _generate_hash_embedding(text: str, dim: int = _EMBED_DIM) -> list[float]:
    """Generate a deterministic hash-based embedding."""
    hash_bytes = hashlib.sha256(text.encode()).digest()
    # Extend to required dimension by repeating hash
    values = list(hash_bytes)
    while len(values) < dim:
        values.extend(hash_bytes)
    # Normalize to [-1, 1] range
    max_val = 255.0
    return [v / max_val - 0.5 for v in values[:dim]]


class _NVIDIAEmbedBackend:
    """Wraps NVIDIA NIM nv-embed-v1 for text embeddings."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client = httpx.Client(timeout=60)

    def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        resp = self._client.post(
            _NVIDIA_EMBED_URL,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"input": texts, "model": "nvidia/nv-embed-v1", "input_type": "passage", "truncate": "END"},
        )
        resp.raise_for_status()
        data = resp.json()
        sorted_items = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in sorted_items]


class _GeminiLLMBackend:
    """Wraps Google Gemini API for LLM purpose generation."""

    def __init__(self, api_key: str, model: str = "gemma-3-27b-it") -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model

    def generate_purpose(self, nodes: list[GraphNode]) -> list[tuple[str, float]]:
        if not nodes:
            return []

        parts: list[str] = []
        for i, n in enumerate(nodes):
            ctx = f"class={n.metadata.get('class', '')}" if n.metadata.get("class") else ""
            doc = f'docstring="{n.docstring}"' if n.docstring else ""
            parts.append(f"[{i}] {n.type.value} {n.name} ({n.signature}) {ctx} {doc}")

        prompt = (
            "You are a code analysis assistant. For each code entity below, "
            "write exactly ONE concise sentence describing its purpose. "
            "Reply with ONLY a numbered list, one line per entity.\n\n" + "\n".join(parts)
        )

        try:
            response = self._client.models.generate_content(model=self._model, contents=prompt)
            text = response.text or ""
            return self._parse_responses(text, len(nodes))
        except Exception as exc:
            log.warning("gemini_purpose_failed", error=str(exc))
            results: list[tuple[str, float]] = []
            for n in nodes:
                if n.docstring:
                    purpose = " ".join(n.docstring.split())[:200]
                    results.append((purpose, 0.6))
                else:
                    results.append(("", 0.0))
            return results

    @staticmethod
    def _parse_responses(text: str, expected: int) -> list[tuple[str, float]]:
        results: list[tuple[str, float]] = []
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            match = re.match(r"^\d+[\.\)\]\:]\s*(.*)", line)
            if match:
                purpose = match.group(1).strip()
                if purpose:
                    results.append((purpose, 0.9))
            elif line.startswith("- "):
                results.append((line[2:].strip(), 0.9))

        while len(results) < expected:
            results.append(("", 0.0))
        return results[:expected]


class _NoOpEnricher(SemanticEnricherInterface):
    """No-op enricher that uses hash embeddings without any LLM calls."""

    def __init__(self, embedding_dim: int = _EMBED_DIM) -> None:
        self._embedding_dim = embedding_dim

    @property
    def has_llm(self) -> bool:
        return False

    async def enrich_node(self, node: GraphNode) -> GraphNode:
        if node.semantic and node.semantic.purpose:
            return node

        key = f"{node.file_path}:{node.name}:{node.start_line}"
        embedding = _generate_hash_embedding(key, self._embedding_dim)
        sem = SemanticInfo(purpose="", embedding=embedding, confidence=0.0)
        return self._with_semantic(node, sem)

    async def enrich_batch(self, nodes: list[GraphNode]) -> list[GraphNode]:
        enriched = []
        for node in nodes:
            if node.semantic and node.semantic.purpose:
                enriched.append(node)
            else:
                enriched.append(await self.enrich_node(node))
        return enriched

    async def embed(self, text: str) -> list[float]:
        return _generate_hash_embedding(text, self._embedding_dim)

    def cache_put(self, node_id: str, sem: SemanticInfo) -> None:
        pass

    def cache_get(self, node_id: str) -> SemanticInfo | None:
        return None

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


class LLMSemanticEnricher(SemanticEnricherInterface):
    """Semantic enricher backed by NVIDIA NIM embeddings and Gemini LLM.

    Set SMP_ENRICHMENT=none to disable LLM enrichment (uses hash embeddings instead).
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemma-3-27b-it",
        embedding_dim: int = _EMBED_DIM,
        cache_max_size: int = 10_000,
    ) -> None:
        self._embedding_dim = embedding_dim
        self._cache: dict[str, SemanticInfo] = {}
        self._cache_order: list[str] = []
        self._cache_max = cache_max_size

        enrichment_mode = os.environ.get("SMP_ENRICHMENT", "full").lower()

        if enrichment_mode == "none":
            log.info("enrichment_disabled", mode="hash_only")
            self._embedder = None
            self._llm = None
            return

        nv_key = api_key or os.environ.get("NV_API")
        if not nv_key:
            log.warning("nv_api_missing_using_hash", reason="NV_API not set, falling back to hash embeddings")
            self._embedder = None
            self._llm = None
            return

        gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not gemini_key:
            log.warning("gemini_key_missing_using_hash", reason="GEMINI_API_KEY not set, falling back to hash embeddings")
            self._embedder = None
            self._llm = None
            return

        self._embedder = _NVIDIAEmbedBackend(api_key=nv_key)
        self._llm = _GeminiLLMBackend(api_key=gemini_key, model=model)
        log.info("llm_backends_active", embedder="nvidia-nv-embed-v1", llm=model)

    @property
    def has_llm(self) -> bool:
        return self._llm is not None

    async def enrich_node(self, node: GraphNode) -> GraphNode:
        if node.semantic and node.semantic.purpose:
            return node

        if self._llm is None or self._embedder is None:
            key = f"{node.file_path}:{node.name}:{node.start_line}"
            embedding = _generate_hash_embedding(key, self._embedding_dim)
            sem = SemanticInfo(purpose="", embedding=embedding, confidence=0.0)
            return self._with_semantic(node, sem)

        if node.id in self._cache:
            return self._with_semantic(node, self._cache[node.id])

        results = self._llm.generate_purpose([node])
        purpose, confidence = results[0] if results else ("", 0.0)

        embed_text = f"{node.name}: {purpose}" if purpose else node.name
        embeddings = self._embedder.generate_embeddings([embed_text])
        embedding = embeddings[0] if embeddings else []

        sem = SemanticInfo(purpose=purpose, embedding=embedding, confidence=confidence)
        self._cache[node.id] = sem
        return self._with_semantic(node, sem)

    async def enrich_batch(self, nodes: list[GraphNode]) -> list[GraphNode]:
        if self._llm is None or self._embedder is None:
            result_nodes = []
            for node in nodes:
                if node.semantic and node.semantic.purpose:
                    result_nodes.append(node)
                else:
                    key = f"{node.file_path}:{node.name}:{node.start_line}"
                    embedding = _generate_hash_embedding(key, self._embedding_dim)
                    sem = SemanticInfo(purpose="", embedding=embedding, confidence=0.0)
                    result_nodes.append(self._with_semantic(node, sem))
            return result_nodes

        to_enrich = [n for n in nodes if not (n.semantic and n.semantic.purpose)]
        if not to_enrich:
            return nodes

        llm_results = self._llm.generate_purpose(to_enrich)
        purposes: list[tuple[str, float]] = []
        for i, _n in enumerate(to_enrich):
            if i < len(llm_results) and llm_results[i][0]:
                purposes.append(llm_results[i])
            else:
                purposes.append(("", 0.0))

        embed_texts = [
            f"{n.name}: {p}" if p else n.name for n, (p, _) in zip(to_enrich, purposes, strict=False)
        ]
        embeddings = self._embedder.generate_embeddings(embed_texts)

        enriched: list[GraphNode] = []
        idx = 0
        for node in nodes:
            if node.semantic and node.semantic.purpose:
                enriched.append(node)
            else:
                purpose, conf = purposes[idx]
                emb = embeddings[idx] if idx < len(embeddings) else []
                sem = SemanticInfo(purpose=purpose, embedding=emb, confidence=conf)
                self._cache[node.id] = sem
                enriched.append(self._with_semantic(node, sem))
                idx += 1

        log.info("batch_enriched", total=len(nodes), enriched=len(to_enrich))
        return enriched

    async def embed(self, text: str) -> list[float]:
        if self._embedder is None:
            return _generate_hash_embedding(text, self._embedding_dim)
        results = self._embedder.generate_embeddings([text])
        if results:
            return results[0]
        return []

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