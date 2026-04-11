"""Telemetry engine for tracking node hotness and usage patterns.

Collects runtime statistics to identify hot code paths and frequently
accessed nodes for optimization and safety decisions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from smp.logging import get_logger

log = get_logger(__name__)

_HOT_THRESHOLD = 10
_HOT_DECAY_SECONDS = 3600


@dataclass
class NodeStats:
    """Statistics for a single node."""

    node_id: str
    hit_count: int = 0
    last_hit_at: str = ""
    avg_response_time_ms: float = 0.0
    error_count: int = 0
    callers: set[str] = field(default_factory=set)

    def touch(self) -> None:
        """Record a hit on this node."""
        self.hit_count += 1
        self.last_hit_at = datetime.now(UTC).isoformat()


@dataclass
class TelemetryConfig:
    """Configuration for telemetry collection."""

    hot_threshold: int = _HOT_THRESHOLD
    decay_seconds: int = _HOT_DECAY_SECONDS
    max_tracked_nodes: int = 10000


class TelemetryEngine:
    """Tracks node access patterns and identifies hot nodes."""

    def __init__(self, config: TelemetryConfig | None = None) -> None:
        self._config = config or TelemetryConfig()
        self._stats: dict[str, NodeStats] = {}
        self._start_time = time.time()

    def record_access(
        self,
        node_id: str,
        caller_id: str | None = None,
        response_time_ms: float = 0.0,
        error: bool = False,
    ) -> None:
        """Record an access to a node."""
        stats = self._stats.get(node_id)
        if not stats:
            if len(self._stats) >= self._config.max_tracked_nodes:
                self._evict_cold()
            stats = NodeStats(node_id=node_id)
            self._stats[node_id] = stats

        stats.touch()
        if caller_id:
            stats.callers.add(caller_id)
        if response_time_ms > 0:
            total = stats.avg_response_time_ms * (stats.hit_count - 1) + response_time_ms
            stats.avg_response_time_ms = total / stats.hit_count
        if error:
            stats.error_count += 1

        log.debug("telemetry_access", node_id=node_id, hit_count=stats.hit_count)

    def get_hot_nodes(self, threshold: int | None = None) -> list[dict[str, Any]]:
        """Return nodes exceeding the hot threshold."""
        hot_threshold = threshold or self._config.hot_threshold
        hot = []

        for node_id, stats in self._stats.items():
            if stats.hit_count >= hot_threshold:
                hot.append(
                    {
                        "node_id": node_id,
                        "hit_count": stats.hit_count,
                        "last_hit_at": stats.last_hit_at,
                        "avg_response_time_ms": stats.avg_response_time_ms,
                        "error_count": stats.error_count,
                        "caller_count": len(stats.callers),
                    }
                )

        hot.sort(key=lambda x: -int(x["hit_count"]))
        return hot

    def get_stats(self, node_id: str) -> dict[str, Any] | None:
        """Get statistics for a specific node."""
        stats = self._stats.get(node_id)
        if not stats:
            return None
        return {
            "node_id": stats.node_id,
            "hit_count": stats.hit_count,
            "last_hit_at": stats.last_hit_at,
            "avg_response_time_ms": stats.avg_response_time_ms,
            "error_count": stats.error_count,
            "caller_count": len(stats.callers),
        }

    def get_summary(self) -> dict[str, Any]:
        """Return overall telemetry summary."""
        total_hits = sum(s.hit_count for s in self._stats.values())
        total_errors = sum(s.error_count for s in self._stats.values())

        return {
            "uptime_seconds": int(time.time() - self._start_time),
            "total_nodes_tracked": len(self._stats),
            "total_hits": total_hits,
            "total_errors": total_errors,
            "hot_node_count": len(self.get_hot_nodes()),
        }

    def decay(self) -> int:
        """Decay old statistics to prevent unbounded growth."""
        cutoff = datetime.now(UTC).timestamp() - self._config.decay_seconds
        cutoff_str = datetime.fromtimestamp(cutoff, tz=UTC).isoformat()

        to_remove = [
            node_id for node_id, stats in self._stats.items() if stats.last_hit_at and stats.last_hit_at < cutoff_str
        ]

        for node_id in to_remove:
            del self._stats[node_id]

        if to_remove:
            log.info("telemetry_decayed", removed=len(to_remove))
        return len(to_remove)

    def _evict_cold(self) -> None:
        """Evict the coldest nodes when at capacity."""
        if not self._stats:
            return

        sorted_nodes = sorted(self._stats.items(), key=lambda x: x[1].hit_count)
        for node_id, _ in sorted_nodes[: len(sorted_nodes) // 10]:
            del self._stats[node_id]

        log.debug("telemetry_evicted", count=len(sorted_nodes) // 10)

    def reset(self) -> None:
        """Clear all telemetry data."""
        self._stats.clear()
        self._start_time = time.time()
        log.info("telemetry_reset")
