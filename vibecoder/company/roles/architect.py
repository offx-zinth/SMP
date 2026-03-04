from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from google import genai
from pydantic import BaseModel, Field, ValidationError

from vibecoder.company.event_bus import AsyncEventBus, Event
from vibecoder.smp.memory import SMPMemory

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BaseAgent:
    name: str
    bus: AsyncEventBus


class ImplementationTicket(BaseModel):
    id: str
    title: str
    description: str
    owner: str = "SeniorSWE"
    acceptance_criteria: list[str] = Field(default_factory=list)


class ImplementationPlan(BaseModel):
    objective: str
    blast_radius_summary: str
    tickets: list[ImplementationTicket] = Field(default_factory=list)


class LeadArchitect(BaseAgent):
    """Principal planner persona that translates feature requests into executable tickets."""

    def __init__(self, *, bus: AsyncEventBus, memory: SMPMemory, gemini_api_key: str) -> None:
        super().__init__(name="LeadArchitect", bus=bus)
        self._memory = memory
        self._client = genai.Client(api_key=gemini_api_key).aio

    def register(self) -> None:
        self.bus.subscribe("new_feature_request", self._on_feature_request)

    async def _on_feature_request(self, event: Event) -> None:
        request = str(event.payload.get("request", "")).strip()
        if not request:
            logger.warning("LeadArchitect received empty request payload")
            return

        blast_radius = await asyncio.to_thread(self._build_blast_radius_context, request)
        plan = await self._generate_plan(request=request, blast_radius=blast_radius)

        await self.bus.publish(
            Event(
                topic="plan_ready",
                sender=self.name,
                payload={"objective": plan.objective, "ticket_count": len(plan.tickets)},
            )
        )

        for ticket in plan.tickets:
            await self.bus.publish(
                Event(topic="ticket_created", sender=self.name, payload=ticket.model_dump(mode="json"))
            )

    def _build_blast_radius_context(self, request: str) -> str:
        files = [
            attrs.get("file_path")
            for _, attrs in self._memory.graph.nodes(data=True)
            if attrs.get("type") == "file" and attrs.get("file_path")
        ]
        contexts: list[str] = []
        for file_path in files[:8]:
            try:
                contexts.append(self._memory.get_compressed_context(str(file_path)))
            except Exception:  # noqa: BLE001
                continue

        if not contexts:
            return json.dumps({"request": request, "graph": "unavailable"})
        return "\n\n".join(contexts)

    async def _generate_plan(self, *, request: str, blast_radius: str) -> ImplementationPlan:
        prompt = (
            "You are LeadArchitect. Produce strict JSON with keys objective, blast_radius_summary, tickets. "
            "Each ticket requires: id, title, description, owner, acceptance_criteria. "
            "Tickets must be implementable by autonomous agents and safe for parallel execution.\n\n"
            f"Feature request:\n{request}\n\n"
            f"SMP blast radius:\n{blast_radius[:18000]}"
        )
        response = await self._client.models.generate_content(model="gemini-3-pro", contents=prompt)
        payload = self._extract_json(response.text or "")

        try:
            return ImplementationPlan.model_validate(payload)
        except ValidationError:
            logger.warning("LeadArchitect falling back to single-ticket plan due to parse failure")
            return ImplementationPlan(
                objective=request,
                blast_radius_summary="Fallback plan due to invalid LLM response.",
                tickets=[
                    ImplementationTicket(
                        id="ticket-1",
                        title="Implement requested feature",
                        description=request,
                        acceptance_criteria=["Feature works as requested", "Relevant tests pass"],
                    )
                ],
            )

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    return {}
        return {}
