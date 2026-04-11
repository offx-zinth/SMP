"""Runtime linker for tracking actual execution paths.

Records CALLS_RUNTIME edges based on telemetry data to build
a runtime call graph that complements the static analysis.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from smp.core.models import RuntimeEdge, RuntimeTrace
from smp.logging import get_logger

log = get_logger(__name__)


@dataclass
class RuntimeCall:
    """A single runtime call observation."""

    source_id: str
    target_id: str
    timestamp: str
    session_id: str
    duration_ms: int = 0


class RuntimeLinker:
    """Tracks and records runtime execution paths."""

    def __init__(self) -> None:
        self._calls: list[RuntimeCall] = []
        self._traces: dict[str, RuntimeTrace] = {}
        self._session_traces: dict[str, list[str]] = defaultdict(list)
        self._call_counts: dict[tuple[str, str], int] = defaultdict(int)

    def record_call(
        self,
        source_id: str,
        target_id: str,
        session_id: str,
        duration_ms: int = 0,
    ) -> RuntimeEdge:
        """Record a runtime call observation."""
        trace_id = f"trace_{uuid.uuid4().hex[:8]}"
        timestamp = datetime.now(UTC).isoformat()

        call = RuntimeCall(
            source_id=source_id,
            target_id=target_id,
            timestamp=timestamp,
            session_id=session_id,
            duration_ms=duration_ms,
        )
        self._calls.append(call)

        key = (source_id, target_id)
        self._call_counts[key] += 1

        edge = RuntimeEdge(
            source_id=source_id,
            target_id=target_id,
            edge_type="CALLS_RUNTIME",
            timestamp=timestamp,
            session_id=session_id,
            trace_id=trace_id,
            duration_ms=duration_ms,
        )

        self._session_traces[session_id].append(trace_id)

        log.debug(
            "runtime_call_recorded",
            source=source_id,
            target=target_id,
            session=session_id,
        )
        return edge

    def start_trace(
        self,
        session_id: str,
        agent_id: str,
    ) -> str:
        """Start a new runtime trace."""
        trace_id = f"trc_{uuid.uuid4().hex[:8]}"
        timestamp = datetime.now(UTC).isoformat()

        trace = RuntimeTrace(
            trace_id=trace_id,
            session_id=session_id,
            agent_id=agent_id,
            started_at=timestamp,
        )
        self._traces[trace_id] = trace

        log.info("trace_started", trace_id=trace_id, session=session_id)
        return trace_id

    def end_trace(self, trace_id: str) -> RuntimeTrace | None:
        """End a runtime trace."""
        trace = self._traces.get(trace_id)
        if not trace:
            return None

        trace.ended_at = datetime.now(UTC).isoformat()

        related_calls = [c for c in self._calls if c.session_id == trace.session_id]
        trace.edges = [
            RuntimeEdge(
                source_id=c.source_id,
                target_id=c.target_id,
                edge_type="CALLS_RUNTIME",
                timestamp=c.timestamp,
                session_id=c.session_id,
                trace_id=trace_id,
                duration_ms=c.duration_ms,
            )
            for c in related_calls
        ]

        visited: set[str] = set()
        for edge in trace.edges:
            visited.add(edge.source_id)
            visited.add(edge.target_id)
        trace.nodes_visited = list(visited)

        log.info(
            "trace_ended",
            trace_id=trace_id,
            edges=len(trace.edges),
            nodes=len(trace.nodes_visited),
        )
        return trace

    def get_trace(self, trace_id: str) -> RuntimeTrace | None:
        """Get trace by ID."""
        return self._traces.get(trace_id)

    def get_session_traces(self, session_id: str) -> list[RuntimeTrace]:
        """Get all traces for a session."""
        trace_ids = self._session_traces.get(session_id, [])
        return [self._traces[tid] for tid in trace_ids if tid in self._traces]

    def get_hot_paths(self, threshold: int = 10) -> list[dict[str, Any]]:
        """Return frequently executed paths."""
        hot = []

        for (source, target), count in self._call_counts.items():
            if count >= threshold:
                hot.append(
                    {
                        "source_id": source,
                        "target_id": target,
                        "call_count": count,
                    }
                )

        hot.sort(key=lambda x: -int(x["call_count"]))
        return hot

    def get_stats(self) -> dict[str, Any]:
        """Return runtime linker statistics."""
        return {
            "total_calls": len(self._calls),
            "unique_paths": len(self._call_counts),
            "active_traces": len(self._traces),
            "sessions_with_traces": len(self._session_traces),
        }

    def clear(self) -> None:
        """Clear all runtime data."""
        self._calls.clear()
        self._traces.clear()
        self._session_traces.clear()
        self._call_counts.clear()
        log.info("runtime_linker_cleared")
