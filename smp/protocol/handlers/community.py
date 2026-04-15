"""Handler for community detection methods."""

from __future__ import annotations

from typing import Any, cast

import msgspec

from smp.core.models import (
    CommunityBoundariesParams,
    CommunityDetectParams,
    CommunityGetParams,
    CommunityListParams,
)
from smp.protocol.handlers.base import MethodHandler


class CommunityDetectHandler(MethodHandler):
    """Handles smp/community/detect method."""

    @property
    def method(self) -> str:
        return "smp/community/detect"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        p = msgspec.convert(params, CommunityDetectParams)
        detector = context["community_detector"]
        return cast(
            dict[str, Any],
            await detector.detect(
                resolutions=p.resolutions or None,
                relationship_types=p.relationship_types or None,
            ),
        )


class CommunityListHandler(MethodHandler):
    """Handles smp/community/list method."""

    @property
    def method(self) -> str:
        return "smp/community/list"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        p = msgspec.convert(params, CommunityListParams)
        detector = context["community_detector"]
        return cast(dict[str, Any], await detector.list_communities(level=p.level))


class CommunityGetHandler(MethodHandler):
    """Handles smp/community/get method."""

    @property
    def method(self) -> str:
        return "smp/community/get"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        p = msgspec.convert(params, CommunityGetParams)
        detector = context["community_detector"]
        result = await detector.get_community(
            community_id=p.community_id,
            node_types=p.node_types or None,
            include_bridges=p.include_bridges,
        )
        return cast(dict[str, Any] | None, result)


class CommunityBoundariesHandler(MethodHandler):
    """Handles smp/community/boundaries method."""

    @property
    def method(self) -> str:
        return "smp/community/boundaries"

    async def handle(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        p = msgspec.convert(params, CommunityBoundariesParams)
        detector = context["community_detector"]
        return cast(dict[str, Any], await detector.get_boundaries(level=p.level, min_coupling=p.min_coupling))
