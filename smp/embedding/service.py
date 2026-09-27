"""Qwen3 embedding service backed by llama-cpp-python.

The Qwen3-Embedding model expects inputs prefixed with an instruction
format: "Instruct: <instruction>\nQuery: <text>" for query embeddings,
and just the document text for document embeddings.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Final

from llama_cpp import Llama

log = logging.getLogger(__name__)

DEFAULT_MODEL_PATH: Final[str] = str(
    Path(__file__).parent.parent.parent / "Qwen3-Embedding-0.6B-GGUF" / "Qwen3-Embedding-0.6B-Q8_0.gguf"
)

SMP_MODEL_PATH = os.environ.get("SMP_MODEL_PATH", DEFAULT_MODEL_PATH)

EMBEDDING_DIM: Final[int] = 1024

# Qwen3 embedding format constants
_INSTRUCT_TEMPLATE: Final[str] = "Instruct: {instruction}\nQuery: {text}"
_DEFAULT_INSTRUCTION: Final[str] = (
    "Given a code snippet, retrieve relevant code snippets that are semantically similar."
)


class QwenEmbeddingService:
    """Thread-safe embedding service using the Qwen3 GGUF model."""

    _instance: QwenEmbeddingService | None = None
    _lock = asyncio.Lock()

    def __init__(
        self,
        model_path: str | None = None,
        n_ctx: int = 2048,
        n_gpu_layers: int = 0,
        n_batch: int = 512,
        verbose: bool = False,
    ) -> None:
        self._model_path = model_path or SMP_MODEL_PATH
        self._n_ctx = n_ctx
        self._n_gpu_layers = n_gpu_layers
        self._n_batch = n_batch
        self._verbose = verbose
        self._model: Llama | None = None
        self._initialised = False
        self._init_lock = asyncio.Lock()

    async def _ensure_initialised(self) -> None:
        """Lazily initialise the model in a thread-safe manner."""
        if self._initialised:
            return
        async with self._init_lock:
            if self._initialised:
                return
            await self._init_model()
            self._initialised = True

    async def _init_model(self) -> None:
        """Load the GGUF model in a thread pool to avoid blocking the event loop."""
        if not Path(self._model_path).exists():
            raise FileNotFoundError(f"Model file not found: {self._model_path}")

        def _load() -> Llama:
            return Llama(
                model_path=self._model_path,
                embedding=True,
                n_ctx=self._n_ctx,
                n_gpu_layers=self._n_gpu_layers,
                n_batch=self._n_batch,
                verbose=self._verbose,
            )

        log.info("embedding_model_loading", extra={"model_path": self._model_path})
        loop = asyncio.get_running_loop()
        model = await loop.run_in_executor(None, _load)
        self._model = model
        log.info("embedding_model_loaded", extra={"dim": EMBEDDING_DIM})

    def _format_query(self, text: str, instruction: str | None = None) -> str:
        """Format text as a query with instruction prefix."""
        instr = instruction or _DEFAULT_INSTRUCTION
        return _INSTRUCT_TEMPLATE.format(instruction=instr, text=text)

    def _format_document(self, text: str) -> str:
        """Format text as a document (no instruction prefix)."""
        return text

    async def embed_query(self, text: str, instruction: str | None = None) -> list[float]:
        """Generate an embedding for a search query."""
        await self._ensure_initialised()
        assert self._model is not None
        model = self._model
        formatted = self._format_query(text, instruction)
        loop = asyncio.get_running_loop()
        embedding = await loop.run_in_executor(None, lambda: model.embed(formatted))
        return list(embedding)

    async def embed_document(self, text: str) -> list[float]:
        """Generate an embedding for a document/code snippet."""
        await self._ensure_initialised()
        assert self._model is not None
        model = self._model
        formatted = self._format_document(text)
        loop = asyncio.get_running_loop()
        embedding = await loop.run_in_executor(None, lambda: model.embed(formatted))
        return list(embedding)

    async def embed_batch(
        self,
        texts: list[str],
        is_query: bool = False,
        instruction: str | None = None,
    ) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        await self._ensure_initialised()
        assert self._model is not None
        model = self._model

        if is_query:
            formatted = [self._format_query(t, instruction) for t in texts]
        else:
            formatted = [self._format_document(t) for t in texts]

        loop = asyncio.get_running_loop()

        def _embed_all() -> list[list[float]]:
            return [list(model.embed(t)) for t in formatted]

        return await loop.run_in_executor(None, _embed_all)

    @property
    def dimension(self) -> int:
        return EMBEDDING_DIM

    async def close(self) -> None:
        """Release model resources."""
        if self._model is not None:
            self._model = None
            self._initialised = False
            log.info("embedding_model_closed")


async def get_embedding_service(
    model_path: str | None = None,
    n_ctx: int = 2048,
    n_gpu_layers: int = 0,
    n_batch: int = 512,
    verbose: bool = False,
) -> QwenEmbeddingService:
    """Get or create the singleton embedding service instance."""
    async with QwenEmbeddingService._lock:
        if QwenEmbeddingService._instance is None:
            QwenEmbeddingService._instance = QwenEmbeddingService(
                model_path=model_path,
                n_ctx=n_ctx,
                n_gpu_layers=n_gpu_layers,
                n_batch=n_batch,
                verbose=verbose,
            )
        return QwenEmbeddingService._instance


@asynccontextmanager
async def embedding_service_context(
    model_path: str | None = None,
    **kwargs: Any,
) -> AsyncIterator[QwenEmbeddingService]:
    """Context manager for embedding service lifecycle."""
    service = await get_embedding_service(model_path, **kwargs)
    try:
        yield service
    finally:
        await service.close()


def build_code_text(node: dict[str, Any]) -> str:
    """Build a text representation of a code node for embedding.

    Combines name, signature, docstring, and file context into a
    single string that captures the semantic meaning of the node.
    """
    parts: list[str] = []

    if node.get("name"):
        parts.append(f"Name: {node['name']}")
    if node.get("signature"):
        parts.append(f"Signature: {node['signature']}")
    if node.get("docstring"):
        parts.append(f"Docstring: {node['docstring']}")
    if node.get("file_path"):
        parts.append(f"File: {node['file_path']}")
    if node.get("type"):
        parts.append(f"Type: {node['type']}")

    return "\n".join(parts)
