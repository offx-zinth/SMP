from __future__ import annotations

import uuid

from smp.logging import get_logger

log = get_logger(__name__)


class EBPFCollector:
    def __init__(self) -> None:
        self._active_traces: dict[str, str] = {}
        self._data: list[dict[str, str | int]] = []

    def start_trace(self, session_id: str) -> str:
        trace_id = str(uuid.uuid4())
        self._active_traces[trace_id] = session_id
        log.info("ebpf_trace_started", trace_id=trace_id, session_id=session_id)
        return trace_id

    def stop_trace(self, trace_id: str) -> None:
        if trace_id in self._active_traces:
            session_id = self._active_traces.pop(trace_id)
            log.info("ebpf_trace_stopped", trace_id=trace_id, session_id=session_id)
        else:
            log.error("ebpf_trace_stop_failed", trace_id=trace_id)

    def get_traces(self) -> list[dict[str, str | int]]:
        return self._data
