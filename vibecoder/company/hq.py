from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from vibecoder.company.event_bus import AsyncEventBus, Event
from vibecoder.company.roles.architect import BaseAgent, LeadArchitect
from vibecoder.company.roles.vision_qa import VisionQAAgent
from vibecoder.company.sandbox import DockerWorkspace
from vibecoder.config import Config
from vibecoder.context import AppContext
from vibecoder.smp.memory import SMPMemory

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DashboardState:
    event_log: deque[str] = field(default_factory=lambda: deque(maxlen=50))
    docker_commands: deque[str] = field(default_factory=lambda: deque(maxlen=20))
    tickets: dict[str, str] = field(default_factory=dict)


class SeniorSWEAgent(BaseAgent):
    """Execution persona that implements tickets inside Docker sandbox."""

    def __init__(self, *, bus: AsyncEventBus, sandbox: DockerWorkspace, state: DashboardState) -> None:
        super().__init__(name="SeniorSWE", bus=bus)
        self._sandbox = sandbox
        self._state = state

    def register(self) -> None:
        self.bus.subscribe("ticket_created", self._on_ticket_created)
        self.bus.subscribe("bug_found", self._on_bug_found)

    async def _on_ticket_created(self, event: Event) -> None:
        ticket_id = str(event.payload.get("id", "unknown"))
        description = str(event.payload.get("description", ""))
        self._state.tickets[ticket_id] = "In Progress"
        command = event.payload.get("command") or "python -m compileall vibecoder"
        self._state.docker_commands.append(f"{ticket_id}: {command}")
        result = await self._sandbox.execute(str(command))

        self._state.tickets[ticket_id] = "Done" if result.exit_code == 0 else "Blocked"
        await self.bus.publish(
            Event(
                topic="ticket_completed",
                sender=self.name,
                payload={
                    "id": ticket_id,
                    "description": description,
                    "requirement": description,
                    "command": command,
                    "exit_code": result.exit_code,
                    "output": result.output,
                },
            )
        )

    async def _on_bug_found(self, event: Event) -> None:
        ticket_id = str(event.payload.get("ticket_id", "unknown"))
        self._state.tickets[ticket_id] = "Rework Required"


class VibeCoderHQ:
    """Executive runtime that wires all personas to an event-driven backbone."""

    def __init__(self, config: Config) -> None:
        self._context = AppContext.from_config(config)
        self._state = DashboardState()
        self._bus = AsyncEventBus(queue_size=1000, worker_count=6)
        self._memory = SMPMemory(self._context)
        self._sandbox = DockerWorkspace(workspace_dir=config.workspace_dir)

        self._architect = LeadArchitect(
            bus=self._bus,
            memory=self._memory,
            gemini_api_key=config.gemini_api_key,
        )
        self._swe = SeniorSWEAgent(bus=self._bus, sandbox=self._sandbox, state=self._state)
        self._vision_qa = VisionQAAgent(
            bus=self._bus,
            gemini_api_key=config.gemini_api_key,
            artifacts_dir=config.workspace_dir / ".vibecoder_artifacts",
        )

    async def run(self, feature_request: str, *, runtime_seconds: int = 25) -> None:
        self._register_subscribers()
        await self._bus.start()
        await self._sandbox.start()

        try:
            with Live(self._render_dashboard(), refresh_per_second=4, console=self._context.console) as live:
                await self._bus.publish(
                    Event(topic="new_feature_request", sender="user", payload={"request": feature_request})
                )
                await self._tick_dashboard(live=live, duration_seconds=runtime_seconds)
        finally:
            await self._sandbox.stop()
            await self._bus.stop()

    def _register_subscribers(self) -> None:
        self._architect.register()
        self._swe.register()
        self._vision_qa.register()
        for topic in [
            "new_feature_request",
            "plan_ready",
            "ticket_created",
            "ticket_completed",
            "qa_passed",
            "bug_found",
        ]:
            self._bus.subscribe(topic, self._capture_event)

    async def _capture_event(self, event: Event) -> None:
        self._state.event_log.appendleft(f"[{event.topic}] {event.sender}: {event.payload}")

    async def _tick_dashboard(self, *, live: Live, duration_seconds: int) -> None:
        for _ in range(duration_seconds * 4):
            live.update(self._render_dashboard())
            await asyncio.sleep(0.25)

    def _render_dashboard(self) -> Layout:
        layout = Layout(name="root")
        layout.split_column(
            Layout(name="top", ratio=2),
            Layout(name="bottom", ratio=1),
        )
        layout["top"].split_row(Layout(name="events"), Layout(name="docker"))
        layout["bottom"].split_row(Layout(name="tickets"))

        event_group = Group(*(Text(line) for line in list(self._state.event_log)[:18]))
        docker_group = Group(*(Text(line) for line in list(self._state.docker_commands)[:12]))

        tickets_table = Table(title="Active Tickets")
        tickets_table.add_column("Ticket")
        tickets_table.add_column("Status")
        for ticket_id, status in self._state.tickets.items():
            tickets_table.add_row(ticket_id, status)

        layout["events"].update(Panel(event_group, title="Event Log"))
        layout["docker"].update(Panel(docker_group, title="Docker Metrics"))
        layout["tickets"].update(Panel(tickets_table, title="Kanban"))
        return layout


async def run_hq(feature_request: str, *, config: Config | None = None) -> None:
    runtime_config = config or Config()
    hq = VibeCoderHQ(runtime_config)
    await hq.run(feature_request)
