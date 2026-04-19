"""Embedding service using NVIDIA NIM or OpenAI."""

from __future__ import annotations

import os
from typing import Any

import httpx

from smp.logging import get_logger

log = get_logger(__name__)


class EmbeddingService:
    """Generate embeddings via NVIDIA NIM or OpenAI."""

    def __init__(
        self,
        provider: str = "nvidia",
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        dimension: int = 768,
    ) -> None:
        self._provider = provider
        self._api_key = api_key or os.environ.get("NVIDIA_NIM_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        self._model = model or os.environ.get("EMBEDDING_MODEL", "nvidia/nv-embed-qa-4")
        self._base_url = base_url or os.environ.get(
            "EMBEDDING_BASE_URL", "https://integrate.api.nvidia.com/v1"
        )
        self._dimension = dimension
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=60.0,
        )
        log.info("embedding_service_connected", provider=self._provider, model=self._model)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        if self._client is None:
            raise RuntimeError("EmbeddingService not connected")

        if self._provider == "nvidia":
            return await self._embed_nvidia(text)
        elif self._provider == "openai":
            return await self._embed_openai(text)
        else:
            raise ValueError(f"Unknown provider: {self._provider}")

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        if self._client is None:
            raise RuntimeError("EmbeddingService not connected")

        if self._provider == "nvidia":
            return await self._embed_batch_nvidia(texts)
        elif self._provider == "openai":
            return await self._embed_batch_openai(texts)
        else:
            raise ValueError(f"Unknown provider: {self._provider}")

    async def _embed_nvidia(self, text: str) -> list[float]:
        payload = {
            "input": text,
            "model": self._model,
        }
        response = await self._client.post("/embeddings", json=payload)
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]

    async def _embed_batch_nvidia(self, texts: list[str]) -> list[list[float]]:
        payload = {
            "input": texts,
            "model": self._model,
        }
        response = await self._client.post("/embeddings", json=payload)
        response.raise_for_status()
        data = response.json()
        return [item["embedding"] for item in data["data"]]

    async def _embed_openai(self, text: str) -> list[float]:
        payload = {
            "input": text,
            "model": self._model,
        }
        response = await self._client.post("/embeddings", json=payload)
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]

    async def _embed_batch_openai(self, texts: list[str]) -> list[list[float]]:
        payload = {
            "input": texts,
            "model": self._model,
        }
        response = await self._client.post("/embeddings", json=payload)
        response.raise_for_status()
        data = response.json()
        return [item["embedding"] for item in data["data"]]


def create_embedding_service() -> EmbeddingService:
    """Create embedding service from environment variables."""
    provider = os.getenv("EMBEDDING_PROVIDER", "nvidia")
    api_key = os.getenv("NVIDIA_NIM_API_KEY") or os.getenv("OPENAI_API_KEY")
    model = os.getenv("EMBEDDING_MODEL")
    base_url = os.getenv("EMBEDDING_BASE_URL")
    dimension = int(os.getenv("EMBEDDING_DIMENSION", "768"))
    return EmbeddingService(provider=provider, api_key=api_key, model=model, base_url=base_url, dimension=dimension)