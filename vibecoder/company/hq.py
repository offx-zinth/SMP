from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field

from rich.console import Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from vibecoder.company.design import SoftwareArchitect, UIUXDesigner
from vibecoder.company.engineering import DevOpsEngineer
from vibecoder.company.event_bus import AsyncEventBus, Event
from vibecoder.company.infrastructure import DockerOrchestrator
from vibecoder.company.leadership import ProductOwner, ProjectManager
from vibecoder.company.quality import QAEngineer
from vibecoder.company.state import CorporateMemory, Epic, Ticket
from vibecoder.config import Config
from vibecoder.context import AppContext
from vibecoder.smp.memory import SMPMemory

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DashboardState:
    event_log: deque[str] = field(default_factory=lambda: deque(maxlen=75))


class VibeCoderHQ:
    """Executive runtime wiring the full autonomous startup sequence."""

    def __init__(self, config: Config) -> None:
        self._context = AppContext.from_config(config)
        self._state = DashboardState()
        self._bus = AsyncEventBus(queue_size=1000, worker_count=8)
        self._memory = CorporateMemory(
            sqlite_path=config.smp_db_dir / "corporate_memory.sqlite3",
            chroma_path=config.smp_db_dir / "chroma",
        )
        self._smp_memory = SMPMemory(self._context)
        self._docker = DockerOrchestrator(project_name="vibecoder")

        self._product_owner = ProductOwner(
            bus=self._bus,
            memory=self._memory,
            gemini_api_key=config.gemini_api_key,
        )
        self._project_manager = ProjectManager(bus=self._bus, memory=self._memory)
        self._architect = SoftwareArchitect(bus=self._bus, memory=self._memory, smp_memory=self._smp_memory)
        self._designer = UIUXDesigner(bus=self._bus, memory=self._memory)
        self._devops = DevOpsEngineer(bus=self._bus, memory=self._memory, orchestrator=self._docker)
        self._qa = QAEngineer(bus=self._bus, memory=self._memory, orchestrator=self._docker, workspace=config.workspace_dir)

        self._executives = [
            self._product_owner,
            self._project_manager,
            self._architect,
            self._designer,
            self._devops,
            self._qa,
        ]

    async def run(self, prompt: str, *, runtime_seconds: int = 25) -> None:
        self._register_subscribers()
        await self._bus.start()
        for actor in self._executives:
            await actor.start()

        try:
            with Live(self._render_dashboard(), refresh_per_second=4, console=self._context.console) as live:
                await self._bus.publish(Event(topic="product_request", sender="user", payload={"prompt": prompt}))
                await self._tick_dashboard(live=live, duration_seconds=runtime_seconds)
        finally:
            for actor in reversed(self._executives):
                await actor.stop()
            await self._bus.stop()
            self._memory.close()

    def _register_subscribers(self) -> None:
        for actor in self._executives:
            actor.register()
        for topic in [
            "product_request",
            "vision_created",
            "epic_created",
            "architecture_ready",
            "ticket_created",
            "ticket_assigned",
            "infra_ready",
            "pull_request_opened",
            "qa_approved",
            "qa_rejected",
        ]:
            self._bus.subscribe(topic, self._capture_event)
        self._bus.subscribe("infra_ready", self._persist_container_metadata)

    async def _capture_event(self, event: Event) -> None:
        self._state.event_log.appendleft(f"[{event.topic}] {event.sender}: {event.payload}")

    async def _persist_container_metadata(self, event: Event) -> None:
        ticket_id = str(event.payload.get("ticket_id", "")).strip()
        image = str(event.payload.get("image", "")).strip()
        network_id = str(event.payload.get("network_id", "")).strip()
        if not ticket_id:
            return

        ticket_model = self._memory.get("tickets", ticket_id)
        if ticket_model is None:
            return

        ticket = Ticket.model_validate(ticket_model.model_dump())
        extra_labels = [
            f"container:{image}" if image else "",
            f"network:{network_id}" if network_id else "",
        ]
        existing = set(ticket.labels)
        for label in extra_labels:
            if label and label not in existing:
                ticket.labels.append(label)
        self._memory.upsert(ticket)

    async def _tick_dashboard(self, *, live: Live, duration_seconds: int) -> None:
        for _ in range(duration_seconds * 4):
            live.update(self._render_dashboard())
            await asyncio.sleep(0.25)

    def _render_dashboard(self) -> Layout:
        layout = Layout(name="root")
        layout.split_column(Layout(name="top", ratio=2), Layout(name="bottom", ratio=1))
        layout["top"].split_row(Layout(name="events", ratio=2), Layout(name="epics", ratio=1))
        layout["bottom"].split_row(Layout(name="tickets", ratio=2), Layout(name="containers", ratio=1))

        events = Group(*(Text(line) for line in list(self._state.event_log)[:18]))
        layout["events"].update(Panel(events, title="Event Stream"))
        layout["epics"].update(Panel(self._build_epics_table(), title="Active Epics"))
        layout["tickets"].update(Panel(self._build_tickets_table(), title="Tickets"))
        layout["containers"].update(Panel(self._build_containers_table(), title="Docker Containers"))
        return layout

    def _build_epics_table(self) -> Table:
        table = Table(expand=True)
        table.add_column("Epic")
        table.add_column("Status")
        table.add_column("Priority", justify="right")

        epics = [Epic.model_validate(item.model_dump()) for item in self._memory.list("epics", limit=25)]
        if not epics:
            table.add_row("No epics yet", "-", "-")
            return table

        for epic in epics:
            table.add_row(epic.title, epic.status, str(epic.priority))
        return table

    def _build_tickets_table(self) -> Table:
        table = Table(expand=True)
        table.add_column("Ticket")
        table.add_column("Role")
        table.add_column("Status")
        table.add_column("Assignee")

        tickets = [Ticket.model_validate(item.model_dump()) for item in self._memory.list("tickets", limit=50)]
        if not tickets:
            table.add_row("No tickets yet", "-", "-", "-")
            return table

        for ticket in tickets:
            table.add_row(ticket.id, ticket.role, ticket.status, ticket.assignee or "unassigned")
        return table

    def _build_containers_table(self) -> Table:
        table = Table(expand=True)
        table.add_column("Ticket")
        table.add_column("Container")
        table.add_column("Network")

        tickets = [Ticket.model_validate(item.model_dump()) for item in self._memory.list("tickets", limit=100)]
        rows = 0
        for ticket in tickets:
            if ticket.role != "infra":
                continue
            image = next((label.split(":", 1)[1] for label in ticket.labels if label.startswith("container:")), "")
            network = next((label.split(":", 1)[1] for label in ticket.labels if label.startswith("network:")), "")
            if not image and not network:
                continue
            table.add_row(ticket.id, image or "-", network or "-")
            rows += 1

        if rows == 0:
            table.add_row("No active containers", "-", "-")
        return table


async def run_hq(prompt: str, *, config: Config | None = None) -> None:
    runtime_config = config or Config()
    hq = VibeCoderHQ(runtime_config)
    await hq.run(prompt)
