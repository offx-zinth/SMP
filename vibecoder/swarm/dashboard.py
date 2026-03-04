from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table


def _build_layout(orchestrator_state: Mapping[str, Any], worker_states: list[Mapping[str, Any]]) -> Layout:
    layout = Layout(name="root")
    layout.split_column(Layout(name="top", ratio=2), Layout(name="bottom", ratio=3))

    plan_text = (
        f"[bold]Intent:[/bold] {orchestrator_state.get('intent', 'N/A')}\n"
        f"[bold]Status:[/bold] {orchestrator_state.get('status', 'planning')}\n"
        f"[bold]Plan Summary:[/bold] {orchestrator_state.get('plan_summary', 'Pending task decomposition')}"
    )
    layout["top"].update(Panel(plan_text, title="Orchestrator Intent & Plan", border_style="cyan"))

    table = Table(title="Parallel Agent Execution", expand=True)
    table.add_column("Worker", style="bold")
    table.add_column("Task")
    table.add_column("Status")
    table.add_column("Iteration", justify="right")
    table.add_column("Last Update")

    for index, worker in enumerate(worker_states[:8], start=1):
        table.add_row(
            worker.get("name", f"worker-{index}"),
            worker.get("task", "unassigned"),
            worker.get("status", "idle"),
            str(worker.get("iteration", 0)),
            worker.get("last_update", ""),
        )

    layout["bottom"].update(Panel(table, border_style="magenta"))
    return layout


async def render_loop(
    orchestrator_state: Mapping[str, Any],
    worker_states: list[Mapping[str, Any]],
    *,
    refresh_hz: float = 8.0,
) -> None:
    """Continuously render swarm execution state while orchestrator runs in background."""
    refresh_period = max(0.05, 1.0 / refresh_hz)
    with Live(_build_layout(orchestrator_state, worker_states), refresh_per_second=refresh_hz, transient=False) as live:
        while True:
            live.update(_build_layout(orchestrator_state, worker_states))
            if orchestrator_state.get("done"):
                break
            await asyncio.sleep(refresh_period)
