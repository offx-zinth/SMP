"""Tiny in-process metrics registry that emits Prometheus exposition format.

Why not :mod:`prometheus_client`?  SMP intentionally keeps its install
footprint small.  The expressive subset we need (counters, gauges,
summary-style histograms) fits in roughly a hundred lines and we
sidestep the multi-process gauge gotchas that come with the official
client.

Concurrency model: every operation grabs a single ``threading.Lock`` —
in practice metric updates are nanoseconds long and never contend with
RPC latency.  If that ever stops being true we can shard the registry
per metric without changing the public API.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Sample:
    labels: tuple[tuple[str, str], ...]
    value: float
    count: int = 0
    sum_value: float = 0.0


@dataclass
class _Metric:
    name: str
    kind: str  # "counter" | "gauge" | "summary"
    help: str
    samples: dict[tuple[tuple[str, str], ...], _Sample] = field(default_factory=dict)


class MetricsRegistry:
    """Thread-safe registry; all methods are O(1) on the metric name."""

    def __init__(self) -> None:
        self._metrics: dict[str, _Metric] = {}
        self._lock = threading.Lock()
        self._start = time.monotonic()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def counter(self, name: str, help: str = "") -> None:
        self._declare(name, "counter", help)

    def gauge(self, name: str, help: str = "") -> None:
        self._declare(name, "gauge", help)

    def summary(self, name: str, help: str = "") -> None:
        self._declare(name, "summary", help)

    def _declare(self, name: str, kind: str, help_text: str) -> None:
        with self._lock:
            metric = self._metrics.get(name)
            if metric is None:
                self._metrics[name] = _Metric(name=name, kind=kind, help=help_text)
            elif metric.kind != kind:
                raise ValueError(f"metric {name!r} already registered as {metric.kind}")

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        self._update(name, "counter", labels, lambda s: setattr(s, "value", s.value + value))

    def set(self, name: str, value: float, **labels: str) -> None:
        self._update(name, "gauge", labels, lambda s: setattr(s, "value", float(value)))

    def observe(self, name: str, value: float, **labels: str) -> None:
        def updater(s: _Sample) -> None:
            s.count += 1
            s.sum_value += float(value)

        self._update(name, "summary", labels, updater)

    def _update(self, name: str, kind: str, labels: dict[str, str], fn: Any) -> None:
        with self._lock:
            metric = self._metrics.get(name)
            if metric is None:
                metric = _Metric(name=name, kind=kind, help="")
                self._metrics[name] = metric
            elif metric.kind != kind:
                raise ValueError(f"metric {name!r} kind mismatch: {metric.kind} vs {kind}")
            key = tuple(sorted(labels.items()))
            sample = metric.samples.get(key)
            if sample is None:
                sample = _Sample(labels=key, value=0.0)
                metric.samples[key] = sample
            fn(sample)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def value(self, name: str, **labels: str) -> float:
        with self._lock:
            metric = self._metrics.get(name)
            if metric is None:
                return 0.0
            key = tuple(sorted(labels.items()))
            sample = metric.samples.get(key)
            return sample.value if sample else 0.0

    def render(self) -> str:
        """Return the full registry as Prometheus exposition text."""
        with self._lock:
            self._metrics.setdefault(
                "smp_uptime_seconds",
                _Metric(name="smp_uptime_seconds", kind="gauge", help="Process uptime in seconds"),
            ).samples[()] = _Sample(labels=(), value=time.monotonic() - self._start)

            lines: list[str] = []
            for name in sorted(self._metrics):
                metric = self._metrics[name]
                if metric.help:
                    lines.append(f"# HELP {name} {metric.help}")
                lines.append(f"# TYPE {name} {metric.kind}")
                if not metric.samples:
                    lines.append(f"{name} 0")
                    continue
                for key in sorted(metric.samples):
                    sample = metric.samples[key]
                    if metric.kind == "summary":
                        lines.append(f"{name}_count{_format_labels(key)} {sample.count}")
                        lines.append(f"{name}_sum{_format_labels(key)} {sample.sum_value:.6f}")
                    else:
                        lines.append(f"{name}{_format_labels(key)} {sample.value:.6f}")
            return "\n".join(lines) + "\n"


def _format_labels(labels: Iterable[tuple[str, str]]) -> str:
    pairs = list(labels)
    if not pairs:
        return ""
    body = ",".join(f'{k}="{_escape(v)}"' for k, v in pairs)
    return "{" + body + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


# ---------------------------------------------------------------------------
# Standard metric set — registered up-front so /metrics is non-empty even
# before the first RPC arrives.
# ---------------------------------------------------------------------------


def install_standard_metrics(registry: MetricsRegistry) -> None:
    registry.counter("smp_rpc_requests_total", "JSON-RPC requests by method and status")
    registry.counter("smp_rpc_errors_total", "JSON-RPC errors by method and code")
    registry.summary("smp_rpc_duration_seconds", "JSON-RPC handler latency")
    registry.gauge("smp_nodes_total", "Live nodes in the graph store")
    registry.gauge("smp_edges_total", "Live edges in the graph store")
    registry.gauge("smp_sessions_active", "Currently open agent sessions")
    registry.gauge("smp_locks_active", "Currently held file leases")
    registry.gauge("smp_journal_size_bytes", "Bytes consumed by the journal data region")
    registry.gauge("smp_uptime_seconds", "Process uptime in seconds")


__all__ = ["MetricsRegistry", "install_standard_metrics"]
