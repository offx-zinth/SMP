"""Base handler interface for JSON-RPC method handlers."""

from __future__ import annotations

import abc
from typing import Any


class MethodHandler(abc.ABC):
    """Abstract base class for JSON-RPC method handlers."""

    @property
    @abc.abstractmethod
    def method(self) -> str:
        """Return the JSON-RPC method name this handler processes."""

    @abc.abstractmethod
    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Handle the method call.

        Args:
            params: The method parameters
            context: Request context (engine, enricher, etc.)

        Returns:
            Result dict or None for notifications

        Raises:
            JsonRpcError: For method-specific errors
        """
