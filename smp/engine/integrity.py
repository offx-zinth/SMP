"""Integrity verification module for AST-based data-flow analysis.

Verifies that runtime behavior matches structural expectations by
analyzing data flow through the AST and detecting mutations.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from smp.logging import get_logger
from smp.store.interfaces import GraphStore

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

    async def run_mutation_test(
        self,
        node_id: str,
        graph_store: GraphStore,
    ) -> IntegrityCheckResult:
        """Run mutation testing on a specific node.

        Mutates operators in the source code and checks if tests still pass.
        """
        node = await graph_store.get_node(node_id)
        if not node:
            log.error("mutation_test_failed", reason="node_not_found", node_id=node_id)
            return IntegrityCheckResult(passed=False, node_id=node_id, checks_run=0)

        file_path = node.file_path
        try:
            with open(file_path) as f:
                lines = f.readlines()
        except OSError as e:
            log.error("mutation_test_failed", reason="file_read_error", error=str(e))
            return IntegrityCheckResult(passed=False, node_id=node_id, checks_run=0)

        mutants_survived = 0
        checks_run = 0
        detected_mutations: list[MutationRecord] = []

        # Simple operator flips
        operators = {"==": "!=", "!=": "==", ">": "<=", "<": ">=", ">=": "<=", "<=": ">"}

        start = max(0, node.structural.start_line - 1)
        end = min(len(lines), node.structural.end_line)

        for i in range(start, end):
            line = lines[i]
            for op, replacement in operators.items():
                if op in line:
                    checks_run += 1
                    original_line = line
                    lines[i] = line.replace(op, replacement, 1)

                    try:
                        with open(file_path, "w") as f:
                            f.writelines(lines)

                        # Run tests
                        result = subprocess.run(["pytest"], capture_output=True, text=True, timeout=30)

                        if result.returncode == 0:
                            mutants_survived += 1
                            mutation = MutationRecord(
                                node_id=node_id,
                                mutation_type="operator_flip",
                                field_name=f"line_{i + 1}",
                                old_value=op,
                                new_value=replacement,
                                detected_at=datetime.now(UTC).isoformat(),
                            )
                            detected_mutations.append(mutation)
                            self._mutations.append(mutation)

                    except (subprocess.TimeoutExpired, OSError) as e:
                        log.warning("mutation_test_warning", error=str(e))
                    finally:
                        lines[i] = original_line
                        with open(file_path, "w") as f:
                            f.writelines(lines)

        passed = mutants_survived == 0

        log.info(
            "mutation_test_completed",
            node_id=node_id,
            passed=passed,
            survived=mutants_survived,
            total=checks_run,
        )

        return IntegrityCheckResult(
            passed=passed,
            node_id=node_id,
            checks_run=checks_run,
            mutations_detected=detected_mutations,
            warnings=[f"{mutants_survived} mutants survived"] if mutants_survived > 0 else [],
        )
