"""SMP Client — Python SDK for the Structural Memory Protocol.

Provides an async client for interacting with the SMP JSON-RPC server.

Usage::

    from smp.client import SMPClient

    async with SMPClient("http://localhost:8420") as client:
        ctx = await client.get_context("src/auth.py")
        results = await client.locate("authentication logic")
        await client.update("src/auth.py", content=new_source)
"""

from __future__ import annotations

from typing import Any

import httpx
import msgspec

from smp.core.models import (
    ContextParams,
    FlowParams,
    ImpactParams,
    JsonRpcRequest,
    JsonRpcResponse,
    Language,
    LocateParams,
    NavigateParams,
    TraceParams,
    UpdateParams,
)


class SMPClientError(Exception):
    """Raised when the SMP server returns an error."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = code
        self.data = data
        super().__init__(f"JSON-RPC error {code}: {message}")


class SMPClient:
    """Async client for the Structural Memory Protocol server.

    Args:
        base_url: Server base URL (e.g. ``"http://localhost:8420"``).
        timeout: Request timeout in seconds.
    """

    def __init__(self, base_url: str = "http://localhost:8420", timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None
        self._timeout = timeout
        self._req_id = 0

    async def connect(self) -> None:
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> SMPClient:
        await self.connect()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    def _ensure_connected(self) -> httpx.AsyncClient:
        if not self._client:
            raise RuntimeError("Client not connected. Use 'async with SMPClient(...)' or call connect().")
        return self._client

    async def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        """Send a JSON-RPC request and return the result."""
        self._req_id += 1
        req = JsonRpcRequest(method=method, params=params, id=self._req_id)
        body = msgspec.json.encode(req)

        client = self._ensure_connected()
        resp = await client.post("/rpc", content=body, headers={"Content-Type": "application/json"})

        if resp.status_code == 204:
            return None

        rpc_resp = msgspec.json.decode(resp.content, type=JsonRpcResponse)
        if rpc_resp.error:
            raise SMPClientError(rpc_resp.error.code, rpc_resp.error.message, rpc_resp.error.data)
        return rpc_resp.result

    # -----------------------------------------------------------------------
    # Protocol methods
    # -----------------------------------------------------------------------

    async def navigate(self, entity_id: str) -> dict[str, Any]:
        """Get a node and its immediate neighbours."""
        return await self._rpc("smp/navigate", msgspec.to_builtins(NavigateParams(query=entity_id)))

    async def trace(
        self,
        start_id: str,
        edge_type: str = "CALLS",
        depth: int = 3,
        direction: str = "outgoing",
    ) -> list[dict[str, Any]]:
        """Recursive traversal (e.g. full call graph)."""
        return await self._rpc(
            "smp/trace",
            msgspec.to_builtins(
                TraceParams(
                    start=start_id,
                    relationship=edge_type,
                    depth=depth,
                    direction=direction,
                )
            ),
        )

    async def get_context(
        self,
        file_path: str,
        scope: str = "edit",
        depth: int = 2,
    ) -> dict[str, Any]:
        """Aggregate structural context for safe editing."""
        return await self._rpc(
            "smp/context",
            msgspec.to_builtins(
                ContextParams(
                    file_path=file_path,
                    scope=scope,
                    depth=depth,
                )
            ),
        )

    async def assess_impact(self, entity_id: str, change_type: str = "delete") -> dict[str, Any]:
        """Find blast radius of a change."""
        return await self._rpc(
            "smp/impact", msgspec.to_builtins(ImpactParams(entity=entity_id, change_type=change_type))
        )

    async def locate(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Search by semantic intent — vector search mapping back to graph nodes."""
        return await self._rpc("smp/locate", msgspec.to_builtins(LocateParams(query=query, top_k=top_k)))

    async def find_flow(self, start: str, end: str, max_depth: int = 20) -> list[list[dict[str, Any]]]:
        """Find paths between two nodes."""
        return await self._rpc(
            "smp/flow",
            msgspec.to_builtins(
                FlowParams(
                    start=start,
                    end=end,
                )
            ),
        )

    async def update(
        self,
        file_path: str,
        content: str = "",
        language: str = "python",
    ) -> dict[str, Any]:
        """Notify the server of a file change — incremental graph update.

        If *content* is provided it is parsed directly; otherwise the server
        reads the file from disk.
        """
        lang = Language(language) if language else Language.PYTHON
        return await self._rpc(
            "smp/update",
            msgspec.to_builtins(
                UpdateParams(
                    file_path=file_path,
                    content=content,
                    language=lang,
                )
            ),
        )

    # -----------------------------------------------------------------------
    # Convenience endpoints
    # -----------------------------------------------------------------------

    async def health(self) -> dict[str, str]:
        """Check server health."""
        client = self._ensure_connected()
        resp = await client.get("/health")
        return resp.json()

    async def stats(self) -> dict[str, int]:
        """Get graph statistics (node/edge counts)."""
        client = self._ensure_connected()
        resp = await client.get("/stats")
        return resp.json()
