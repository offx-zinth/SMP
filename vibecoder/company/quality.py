from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from vibecoder.company.event_bus import Event
from vibecoder.company.infrastructure import DockerOrchestrator
from vibecoder.company.leadership import ActorMessage, BaseActor
from vibecoder.company.state import PullRequest, Ticket

logger = logging.getLogger(__name__)


class QAEngineer(BaseActor):
    """Validates PRs with containerized quality gates in isolated runtime sandboxes."""

    def __init__(
        self,
        *,
        bus,
        memory,
        orchestrator: DockerOrchestrator | None = None,
        workspace: Path | None = None,
    ) -> None:
        super().__init__(name="QAEngineer", bus=bus, memory=memory)
        self._orchestrator = orchestrator or DockerOrchestrator()
        self.workspace = workspace or Path.cwd()

    def register(self) -> None:
        self.bus.subscribe("pull_request_opened", self._enqueue)

    async def _enqueue(self, event: Event) -> None:
        await self.inbox.put(ActorMessage(topic="review_pr", payload=event.payload, sender=event.sender))

    async def handle_message(self, message: ActorMessage) -> None:
        if message.topic != "review_pr":
            return

        pr = PullRequest.model_validate(message.payload)
        ticket_model = self.memory.get("tickets", pr.ticket_id)
        if ticket_model is None:
            return
        ticket = Ticket.model_validate(ticket_model.model_dump())

        status, details = await asyncio.to_thread(self._run_quality_suite, ticket)
        pr.checks["qa"] = status
        pr.status = "merged" if status == "APPROVED" else "changes_requested"
        self.memory.upsert(pr)

        if status == "APPROVED":
            ticket.status = "done"
            self.memory.upsert(ticket)
            await self.bus.publish(Event(topic="qa_approved", sender=self.name, payload={"pr_id": pr.id, "details": details}))
        else:
            ticket.status = "blocked"
            self.memory.upsert(ticket)
            await self.bus.publish(
                Event(
                    topic="qa_rejected",
                    sender=self.name,
                    payload={
                        "epic_id": ticket.epic_id,
                        "title": ticket.title,
                        "reason": details,
                        "bug_id": f"bug-{uuid.uuid4().hex[:8]}",
                    },
                )
            )

    def _run_quality_suite(self, ticket: Ticket) -> tuple[str, str]:
        try:
            logs = self._orchestrator.run_container(
                image="python:3.11",
                command="pytest",
                working_dir="/workspace",
            )
        except RuntimeError as exc:
            details = str(exc).strip()
            return "REJECTED", details or "Containerized pytest execution failed"

        output = logs.strip()
        lowered = output.lower()
        failed_markers = ["failed", "error", "traceback", "no tests ran"]
        if any(marker in lowered for marker in failed_markers):
            return "REJECTED", output or f"pytest failed for ticket {ticket.id}"
        return "APPROVED", output or "All containerized quality checks passed"
