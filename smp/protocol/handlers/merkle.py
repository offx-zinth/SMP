"""Handler for Merkle index and sync methods."""

from __future__ import annotations

from typing import Any, cast

from smp.protocol.handlers.base import MethodHandler


class SyncHandler(MethodHandler):
    """Handles smp/sync method."""

    @property
    def method(self) -> str:
        return "smp/sync"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        remote_hash = params.get("remote_hash", "")
        index = context["merkle_index"]
        # MerkleIndex.sync returns dict[str, set[str]] | None
        result = index.sync(remote_hash)
        if result is None:
            return {"status": "in_sync"}
        return {"status": "out_of_sync", "diff": result}


class MerkleTreeHandler(MethodHandler):
    """Handles smp/merkle/tree method."""

    @property
    def method(self) -> str:
        return "smp/merkle/tree"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        index = context["merkle_index"]
        tree = index._tree
        return {"hash": tree.hash()}


class IndexExportHandler(MethodHandler):
    """Handles smp/index/export method."""

    @property
    def method(self) -> str:
        return "smp/index/export"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        index = context["merkle_index"]
        tree = index._tree
        return cast(dict[str, Any], tree.export())


class IndexImportHandler(MethodHandler):
    """Handles smp/index/import method."""

    @property
    def method(self) -> str:
        return "smp/index/import"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        data = params.get("data", {})
        index = context["merkle_index"]
        tree = index._tree
        tree.import_data(data)
        return {"success": True}
