from __future__ import annotations

import logging
import uuid

from vibecoder.company.design import SoftwareArchitect as SoftwareArchitectV1
from vibecoder.company.engineering_v2 import summarize_escalation
from vibecoder.company.event_bus import Event
from vibecoder.company.leadership import ActorMessage, BaseActor
from vibecoder.company.state import CorporateMemory, Epic, SystemArchitecture, Ticket

logger = logging.getLogger(__name__)


class SoftwareArchitect(SoftwareArchitectV1):
    """Architect with anti-deadlock remediation by listening to escalation events."""

    def register(self) -> None:
        super().register()
        self.bus.subscribe("ticket_escalated", self._enqueue)

    async def handle_message(self, message: ActorMessage) -> None:
        if message.topic == "ticket_escalated":
            await self._handle_escalation(message)
            return
        await super().handle_message(message)

    async def _handle_escalation(self, message: ActorMessage) -> None:
        payload = message.payload
        ticket_id = str(payload.get("ticket_id", ""))
        ticket_raw = self.memory.get("tickets", ticket_id)
        if ticket_raw is None:
            logger.warning("Escalation for unknown ticket_id=%s", ticket_id)
            return

        ticket = Ticket.model_validate(ticket_raw.model_dump())
        epic_raw = self.memory.get("epics", ticket.epic_id)
        epic = Epic.model_validate(epic_raw.model_dump()) if epic_raw else None

        architecture = SystemArchitecture(
            id=f"arch-{uuid.uuid4().hex[:8]}",
            vision_id=epic.vision_id if epic else "unknown",
            title=f"Escalation Remediation for {ticket.title}",
            overview=(
                "Architecture updated after developer deadlock. "
                f"Escalation details:\n{summarize_escalation(payload)}"
            ),
            api_schemas={"guidance": {"enforce_layers": True, "error_budget": "strict"}},
            data_models={"Ticket": Ticket.model_json_schema()},
            database_schema={"note": "No schema changes required unless specified by remediation."},
            integration_points=["Event bus", "Persistent shell", "Pre-flight diagnostics"],
            risks=["Circular dependencies", "API mismatch", "Ambiguous acceptance criteria"],
        )
        self.memory.upsert(architecture)
        await self.bus.publish(
            Event(
                topic="architecture_updated",
                sender=self.name,
                payload={
                    "ticket_id": ticket.id,
                    "architecture_id": architecture.id,
                    "reason": "ticket_escalated",
                    "last_error": payload.get("last_error", ""),
                },
            )
        )


class ProjectManager(BaseActor):
    """PM that re-queues escalated tickets after architectural remediation."""

    def __init__(self, *, bus, memory: CorporateMemory) -> None:
        super().__init__(name="ProjectManagerV2", bus=bus, memory=memory)

    def register(self) -> None:
        self.bus.subscribe("ticket_escalated", self._enqueue)
        self.bus.subscribe("architecture_updated", self._enqueue)

    async def _enqueue(self, event: Event) -> None:
        await self.inbox.put(ActorMessage(topic=event.topic, payload=event.payload, sender=event.sender))

    async def handle_message(self, message: ActorMessage) -> None:
        if message.topic == "ticket_escalated":
            logger.warning("Received escalation; waiting for architecture update: %s", message.payload)
            return

        if message.topic != "architecture_updated":
            return

        ticket_id = str(message.payload.get("ticket_id", ""))
        ticket_raw = self.memory.get("tickets", ticket_id)
        if ticket_raw is None:
            logger.warning("Cannot retry missing ticket_id=%s", ticket_id)
            return

        ticket = Ticket.model_validate(ticket_raw.model_dump())
        ticket.status = "todo"
        ticket.assignee = None
        ticket.labels = [label for label in ticket.labels if label != "escalated"]
        self.memory.upsert(ticket)
        await self.bus.publish(
            Event(
                topic="ticket_retry_requested",
                sender=self.name,
                payload={
                    "ticket_id": ticket.id,
                    "architecture_id": message.payload.get("architecture_id", ""),
                    "attempt_counter": 0,
                },
            )
        )


__all__ = ["ProjectManager", "SoftwareArchitect"]
