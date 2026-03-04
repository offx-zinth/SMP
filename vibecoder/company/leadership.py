from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from google import genai

from vibecoder.company.event_bus import AsyncEventBus, Event
from vibecoder.company.state import CorporateMemory, Epic, ProductVision, Ticket

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ActorMessage:
    topic: str
    payload: dict[str, Any]
    sender: str = "system"


class BaseActor:
    """Actor-model base with dedicated asyncio.Queue inbox."""

    def __init__(self, *, name: str, bus: AsyncEventBus, memory: CorporateMemory) -> None:
        self.name = name
        self.bus = bus
        self.memory = memory
        self.inbox: asyncio.Queue[ActorMessage] = asyncio.Queue(maxsize=500)
        self._task: asyncio.Task[None] | None = None
        self._running = False

    def register(self) -> None:
        raise NotImplementedError

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name=f"actor-{self.name}")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while self._running:
            message = await self.inbox.get()
            try:
                await self.handle_message(message)
            except Exception:  # noqa: BLE001
                logger.exception("Actor %s failed to process topic=%s", self.name, message.topic)
            finally:
                self.inbox.task_done()

    async def handle_message(self, message: ActorMessage) -> None:
        raise NotImplementedError


class ProductOwner(BaseActor):
    """Converts user prompts into strategic product vision and major epics."""

    def __init__(self, *, bus: AsyncEventBus, memory: CorporateMemory, gemini_api_key: str) -> None:
        super().__init__(name="ProductOwner", bus=bus, memory=memory)
        self._client = genai.Client(api_key=gemini_api_key).aio

    def register(self) -> None:
        self.bus.subscribe("product_request", self._enqueue)

    async def _enqueue(self, event: Event) -> None:
        await self.inbox.put(ActorMessage(topic=event.topic, payload=event.payload, sender=event.sender))

    async def handle_message(self, message: ActorMessage) -> None:
        prompt = str(message.payload.get("prompt", "")).strip()
        if not prompt:
            return

        vision, epics = await self._create_vision_and_epics(prompt)
        self.memory.upsert(vision)
        for epic in epics:
            self.memory.upsert(epic)
            await self.bus.publish(Event(topic="epic_created", sender=self.name, payload=epic.model_dump(mode="json")))

        await self.bus.publish(
            Event(
                topic="vision_created",
                sender=self.name,
                payload={"vision_id": vision.id, "epic_count": len(epics)},
            )
        )

    async def _create_vision_and_epics(self, prompt: str) -> tuple[ProductVision, list[Epic]]:
        instruction = (
            "You are Product Owner. Return strict JSON with keys: product_vision and epics. "
            "product_vision contains project_name, problem_statement, target_users, goals, non_goals, "
            "constraints, success_metrics. epics is an array of 5-10 objects each with title, summary, "
            "priority, dependencies, acceptance_criteria."
        )
        response = await self._client.models.generate_content(
            model="gemini-3-pro", contents=f"{instruction}\n\nUser Prompt:\n{prompt}"
        )
        payload = self._safe_json(response.text or "")

        vision_id = f"vision-{uuid.uuid4().hex[:8]}"
        raw_vision = payload.get("product_vision", {})
        vision = ProductVision(
            id=vision_id,
            project_name=str(raw_vision.get("project_name", "Autonomous Project")),
            problem_statement=str(raw_vision.get("problem_statement", prompt)),
            target_users=[str(item) for item in raw_vision.get("target_users", [])],
            goals=[str(item) for item in raw_vision.get("goals", [])],
            non_goals=[str(item) for item in raw_vision.get("non_goals", [])],
            constraints=[str(item) for item in raw_vision.get("constraints", [])],
            success_metrics=[str(item) for item in raw_vision.get("success_metrics", [])],
        )

        epics: list[Epic] = []
        for idx, raw_epic in enumerate(payload.get("epics", [])[:10], start=1):
            epics.append(
                Epic(
                    id=f"epic-{uuid.uuid4().hex[:8]}",
                    vision_id=vision_id,
                    title=str(raw_epic.get("title", f"Epic {idx}")),
                    summary=str(raw_epic.get("summary", "")),
                    priority=int(raw_epic.get("priority", idx * 10)),
                    dependencies=[str(dep) for dep in raw_epic.get("dependencies", [])],
                    acceptance_criteria=[str(c) for c in raw_epic.get("acceptance_criteria", [])],
                )
            )

        if not epics:
            epics.append(
                Epic(
                    id=f"epic-{uuid.uuid4().hex[:8]}",
                    vision_id=vision_id,
                    title="Initial Delivery",
                    summary=prompt,
                    priority=10,
                )
            )
        return vision, epics

    @staticmethod
    def _safe_json(text: str) -> dict[str, Any]:
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    pass
        return {}


class ProjectManager(BaseActor):
    """Transforms epics into dependency-aware tickets and spawns developers dynamically."""

    def __init__(self, *, bus: AsyncEventBus, memory: CorporateMemory) -> None:
        super().__init__(name="ProjectManager", bus=bus, memory=memory)
        self._spawned_agents: dict[str, str] = {}

    def register(self) -> None:
        self.bus.subscribe("epic_created", self._enqueue)
        self.bus.subscribe("qa_rejected", self._enqueue)

    async def _enqueue(self, event: Event) -> None:
        await self.inbox.put(ActorMessage(topic=event.topic, payload=event.payload, sender=event.sender))

    async def handle_message(self, message: ActorMessage) -> None:
        if message.topic == "epic_created":
            epic = Epic.model_validate(message.payload)
            tickets = self._break_down_epic(epic)
            for ticket in tickets:
                self.memory.upsert(ticket)
                await self.bus.publish(Event(topic="ticket_created", sender=self.name, payload=ticket.model_dump(mode="json")))
            await self._assign_ready_tickets()
            return

        if message.topic == "qa_rejected":
            bug_ticket = Ticket(
                id=f"ticket-{uuid.uuid4().hex[:8]}",
                epic_id=str(message.payload.get("epic_id", "unknown-epic")),
                title=f"Bugfix: {message.payload.get('title', 'QA failure')}",
                description=str(message.payload.get("reason", "Resolve QA defects")),
                role="backend",
                priority=5,
                labels=["bug", "qa-regression"],
            )
            self.memory.upsert(bug_ticket)
            await self.bus.publish(Event(topic="ticket_created", sender=self.name, payload=bug_ticket.model_dump(mode="json")))
            await self._assign_ready_tickets()

    async def _assign_ready_tickets(self) -> None:
        all_tickets = [Ticket.model_validate(item.model_dump()) for item in self.memory.list("tickets", limit=500)]
        completed = {ticket.id for ticket in all_tickets if ticket.status == "done"}

        for ticket in sorted(all_tickets, key=lambda ticket: ticket.priority):
            if ticket.status not in {"todo", "blocked"}:
                continue
            if any(dep not in completed for dep in ticket.dependencies):
                ticket.status = "blocked"
                self.memory.upsert(ticket)
                continue

            ticket.status = "in_progress"
            agent_name = await self._spawn_developer(ticket)
            ticket.assignee = agent_name
            self.memory.upsert(ticket)
            await self.bus.publish(
                Event(topic="ticket_assigned", sender=self.name, payload={"ticket_id": ticket.id, "assignee": agent_name})
            )

    async def _spawn_developer(self, ticket: Ticket) -> str:
        from vibecoder.company.engineering import DeveloperAgent

        agent_name = f"DeveloperAgent-{ticket.role}-{uuid.uuid4().hex[:6]}"
        agent = DeveloperAgent(name=agent_name, role=ticket.role, bus=self.bus, memory=self.memory)
        agent.register()
        await agent.start()
        self._spawned_agents[agent_name] = ticket.id
        await agent.inbox.put(ActorMessage(topic="execute_ticket", payload=ticket.model_dump(mode="json"), sender=self.name))
        return agent_name

    def _break_down_epic(self, epic: Epic) -> list[Ticket]:
        roles = ["backend", "frontend", "infra", "qa"]
        tickets: list[Ticket] = []
        previous_id: str | None = None
        for index, role in enumerate(roles, start=1):
            ticket_id = f"ticket-{uuid.uuid4().hex[:8]}"
            dependencies = [previous_id] if previous_id else []
            ticket = Ticket(
                id=ticket_id,
                epic_id=epic.id,
                title=f"{epic.title}: {role.upper()} implementation",
                description=f"{epic.summary}\n\nRole focus: {role}",
                role=role,
                priority=epic.priority + index,
                dependencies=dependencies,
                acceptance_criteria=epic.acceptance_criteria,
            )
            tickets.append(ticket)
            previous_id = ticket_id
        return tickets
