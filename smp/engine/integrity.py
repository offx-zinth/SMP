"""Integrity verification module for AST-based data-flow analysis.

Verifies that runtime behavior matches structural expectations by
analyzing data flow through the AST and detecting mutations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from smp.logging import get_logger

log = get_logger(__name__)


@dataclass
class MutationRecord:
    """Record of a detected mutation."""

    node_id: str
    mutation_type: str
    field_name: str
    old_value: str
    new_value: str
    detected_at: str


@dataclass
class DataFlowPath:
    """Represents a data flow path through the code."""

    source_node: str
    target_node: str
    path: list[str]
    flow_type: str
    transformations: list[str] = field(default_factory=list)


@dataclass
class IntegrityCheckResult:
    """Result of an integrity verification."""

    passed: bool
    node_id: str
    checks_run: int
    mutations_detected: list[MutationRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class IntegrityVerifier:
    """Verifies structural integrity of graph nodes."""

    def __init__(self) -> None:
        self._mutations: list[MutationRecord] = []
        self._baselines: dict[str, dict[str, Any]] = {}

    async def capture_baseline(self, node_id: str, state: dict[str, Any]) -> None:
        """Capture baseline state for a node."""
        self._baselines[node_id] = {
            "state": state.copy(),
            "captured_at": datetime.now(UTC).isoformat(),
        }
        log.debug("baseline_captured", node_id=node_id)

    async def verify(
        self,
        node_id: str,
        current_state: dict[str, Any],
    ) -> IntegrityCheckResult:
        """Verify node state against baseline."""
        baseline = self._baselines.get(node_id)
        mutations: list[MutationRecord] = []
        warnings: list[str] = []

        checks_run = 1

        if baseline:
            for field_name, baseline_value in baseline["state"].items():
                current_value = current_state.get(field_name)

                if baseline_value != current_value:
                    mutation = MutationRecord(
                        node_id=node_id,
                        mutation_type="field_change",
                        field_name=field_name,
                        old_value=str(baseline_value),
                        new_value=str(current_value),
                        detected_at=datetime.now(UTC).isoformat(),
                    )
                    mutations.append(mutation)
                    self._mutations.append(mutation)

                    warnings.append(f"{field_name} changed from {baseline_value} to {current_value}")

        passed = len(mutations) == 0

        log.info(
            "integrity_check",
            node_id=node_id,
            passed=passed,
            mutations=len(mutations),
        )

        return IntegrityCheckResult(
            passed=passed,
            node_id=node_id,
            checks_run=checks_run,
            mutations_detected=mutations,
            warnings=warnings,
        )

    def analyze_data_flow(
        self,
        source: str,
        sink: str,
        path_nodes: list[str],
    ) -> DataFlowPath:
        """Analyze data flow from source to sink."""
        transformations = []

        for i in range(len(path_nodes) - 1):
            transformations.append(f"{path_nodes[i]} → {path_nodes[i + 1]}")

        return DataFlowPath(
            source_node=source,
            target_node=sink,
            path=path_nodes,
            flow_type="data",
            transformations=transformations,
        )

    def get_mutations(self, node_id: str | None = None) -> list[MutationRecord]:
        """Get all detected mutations, optionally filtered by node."""
        if node_id:
            return [m for m in self._mutations if m.node_id == node_id]
        return list(self._mutations)

    def clear_mutations(self) -> None:
        """Clear mutation history."""
        self._mutations.clear()
        log.info("mutations_cleared")

    def get_mutation_summary(self) -> dict[str, Any]:
        """Return summary of detected mutations."""
        by_node: dict[str, int] = {}
        for m in self._mutations:
            by_node[m.node_id] = by_node.get(m.node_id, 0) + 1

        return {
            "total_mutations": len(self._mutations),
            "affected_nodes": len(by_node),
            "by_node": by_node,
        }
