from __future__ import annotations

import logging
import uuid
from typing import Any

from vibecoder.company.event_bus import Event
from vibecoder.company.leadership import ActorMessage, BaseActor
from vibecoder.company.state import CorporateMemory, Epic, SystemArchitecture, Ticket

logger = logging.getLogger(__name__)


class SoftwareArchitect(BaseActor):
    """Produces executable architecture docs from epics and memory graph context."""

    def __init__(self, *, bus, memory: CorporateMemory, smp_memory: Any | None = None) -> None:
        super().__init__(name="SoftwareArchitect", bus=bus, memory=memory)
        self._smp_memory = smp_memory

    def register(self) -> None:
        self.bus.subscribe("epic_created", self._enqueue)

    async def _enqueue(self, event: Event) -> None:
        await self.inbox.put(ActorMessage(topic=event.topic, payload=event.payload, sender=event.sender))

    async def handle_message(self, message: ActorMessage) -> None:
        if message.topic != "epic_created":
            return

        epic = Epic.model_validate(message.payload)
        context = self._read_smp_context(epic.summary)
        architecture = SystemArchitecture(
            id=f"arch-{uuid.uuid4().hex[:8]}",
            vision_id=epic.vision_id,
            title=f"Architecture for {epic.title}",
            overview=f"{epic.summary}\n\nSMP Context:\n{context}",
            api_schemas={
                "/health": {"method": "GET", "response": {"status": "ok"}},
                "/api/epics/{id}": {"method": "GET", "response": {"epic": "Epic"}},
            },
            data_models={
                "Epic": Epic.model_json_schema(),
                "Ticket": Ticket.model_json_schema(),
            },
            database_schema={
                "tables": ["product_visions", "system_architectures", "epics", "tickets", "pull_requests"],
                "storage": "sqlite",
            },
            integration_points=["Gemini for planning", "Docker runtime for execution", "Event bus for workflow"],
            risks=["Prompt variance", "Container resource exhaustion", "Dependency deadlocks"],
        )
        self.memory.upsert(architecture)
        await self.bus.publish(
            Event(topic="architecture_ready", sender=self.name, payload=architecture.model_dump(mode="json"))
        )

    def _read_smp_context(self, query: str) -> str:
        if self._smp_memory is None:
            return "SMP memory not configured"
        try:
            return str(self._smp_memory.get_compressed_context(query))[:2000]
        except Exception:  # noqa: BLE001
            logger.exception("Failed to read SMP memory context")
            return "SMP context unavailable"


class UIUXDesigner(BaseActor):
    """Creates design system artifacts for all user-facing tickets."""

    def register(self) -> None:
        self.bus.subscribe("ticket_created", self._enqueue)

    async def _enqueue(self, event: Event) -> None:
        await self.inbox.put(ActorMessage(topic=event.topic, payload=event.payload, sender=event.sender))

    async def handle_message(self, message: ActorMessage) -> None:
        if message.topic != "ticket_created":
            return

        ticket = Ticket.model_validate(message.payload)
        if ticket.role != "frontend":
            return

        spec = {
            "ticket_id": ticket.id,
            "design_tokens": {
                "colors": {"primary": "#4F46E5", "surface": "#0B1020", "text": "#E2E8F0"},
                "spacing": {"xs": 4, "sm": 8, "md": 16, "lg": 24},
                "radius": {"card": 12, "button": 8},
                "typography": {"font_family": "Inter", "heading_weight": 700, "body_weight": 400},
            },
            "wireframe": [
                "Header with product identity and active sprint details",
                "Main canvas split into task board and artifact insights",
                "Footer showing agent status and event stream",
            ],
            "components": ["PrimaryButton", "TicketCard", "DependencyGraph", "BuildStatusChip"],
        }
        await self.bus.publish(Event(topic="ui_spec_ready", sender=self.name, payload=spec))
