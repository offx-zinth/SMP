from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from google import genai

from vibecoder.agent.fuzzy_editor import EditFailedException, apply_edit_fuzzy, parse_search_replace_blocks
from vibecoder.company.event_bus import AsyncEventBus, Event
from vibecoder.company.infrastructure import DockerOrchestrator
from vibecoder.company.leadership import ActorMessage, BaseActor
from vibecoder.company.state import CorporateMemory, PullRequest, SystemArchitecture, Ticket

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PlannedEdits:
    file_path: Path
    model_output: str


class DeveloperAgent(BaseActor):
    """Generic FE/BE developer that executes tickets and emits structured PR payloads."""

    def __init__(
        self,
        *,
        name: str,
        role: str,
        bus: AsyncEventBus,
        memory: CorporateMemory,
        workspace: Path | None = None,
        gemini_api_key: str | None = None,
    ) -> None:
        super().__init__(name=name, bus=bus, memory=memory)
        self.role = role
        self.workspace = workspace or Path.cwd()
        api_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise ValueError("DeveloperAgent requires Gemini API key via constructor or GEMINI_API_KEY env var")
        self._client = genai.Client(api_key=api_key).aio

    def register(self) -> None:
        self.bus.subscribe("ticket_assigned", self._enqueue)

    async def _enqueue(self, event: Event) -> None:
        if event.payload.get("assignee") != self.name:
            return
        ticket_id = str(event.payload.get("ticket_id", ""))
        ticket = self.memory.get("tickets", ticket_id)
        if ticket is None:
            return
        await self.inbox.put(ActorMessage(topic="execute_ticket", payload=ticket.model_dump(mode="json"), sender=event.sender))

    async def handle_message(self, message: ActorMessage) -> None:
        if message.topic != "execute_ticket":
            return

        ticket = Ticket.model_validate(message.payload)
        architectures = self.memory.list("system_architectures", limit=1)
        architecture = SystemArchitecture.model_validate(architectures[0].model_dump()) if architectures else None

        changed_files: list[str] = []
        try:
            changed_files = await self._implement_ticket(ticket=ticket, architecture=architecture)
            pr = PullRequest(
                id=f"pr-{uuid.uuid4().hex[:8]}",
                ticket_id=ticket.id,
                title=f"[{self.role}] {ticket.title}",
                description=f"Automated implementation by {self.name}",
                branch=f"auto/{ticket.id}",
                files_changed=changed_files,
                checks={"unit": "pending", "lint": "pending"},
            )
            self.memory.upsert(pr)

            ticket.status = "review"
            self.memory.upsert(ticket)
            await self.bus.publish(Event(topic="pull_request_opened", sender=self.name, payload=pr.model_dump(mode="json")))
        except Exception as exc:  # noqa: BLE001
            logger.exception("DeveloperAgent %s failed ticket=%s", self.name, ticket.id)
            ticket.status = "blocked"
            self.memory.upsert(ticket)
            await self.bus.publish(
                Event(
                    topic="qa_rejected",
                    sender=self.name,
                    payload={
                        "epic_id": ticket.epic_id,
                        "title": ticket.title,
                        "reason": f"Implementation failure: {exc}",
                        "files": changed_files,
                    },
                )
            )
        finally:
            self._trigger_self_cleanup()

    async def _implement_ticket(self, *, ticket: Ticket, architecture: SystemArchitecture | None) -> list[str]:
        system_prompt = self._build_system_prompt(ticket=ticket, architecture=architecture)
        response = await self._client.models.generate_content(
            model="gemini-3-pro",
            contents=system_prompt,
        )
        model_text = (response.text or "").strip()
        if not model_text:
            raise RuntimeError("Gemini returned empty implementation response")

        edits = self._parse_file_scoped_blocks(model_text)
        if not edits:
            raise RuntimeError("No valid file edits parsed from Gemini response")

        changed_files: list[str] = []
        for edit in edits:
            target = edit.file_path
            if not target.exists():
                raise FileNotFoundError(f"Model referenced missing file: {target}")

            original = target.read_text(encoding="utf-8")
            updated = original
            for block in parse_search_replace_blocks(edit.model_output):
                updated = apply_edit_fuzzy(updated, block.search, block.replace, threshold=0.85)

            if updated != original:
                target.write_text(updated, encoding="utf-8")
                changed_files.append(str(target.relative_to(self.workspace)))

        if not changed_files:
            raise EditFailedException("Parsed edits did not modify any files")
        return changed_files

    def _build_system_prompt(self, *, ticket: Ticket, architecture: SystemArchitecture | None) -> str:
        architecture_blob = architecture.model_dump_json(indent=2) if architecture else "{}"
        return (
            "You are a principal software engineer implementing a production ticket. "
            "Return ONLY file-scoped SEARCH/REPLACE edits in this exact format:\n"
            "FILE: relative/path.py\n"
            "<<<<<<< SEARCH\n"
            "<existing exact snippet>\n"
            "=======\n"
            "<replacement snippet>\n"
            ">>>>>>> REPLACE\n\n"
            "Do not add prose, markdown explanations, or code fences. "
            "Use only files that already exist.\n\n"
            f"Ticket ID: {ticket.id}\n"
            f"Role: {self.role}\n"
            f"Title: {ticket.title}\n"
            f"Description:\n{ticket.description}\n\n"
            f"Acceptance Criteria: {ticket.acceptance_criteria}\n"
            f"SystemArchitecture:\n{architecture_blob}\n"
        )

    def _parse_file_scoped_blocks(self, model_text: str) -> list[PlannedEdits]:
        chunks: list[PlannedEdits] = []
        current_file: Path | None = None
        current_lines: list[str] = []

        def flush_current() -> None:
            if current_file is None or not current_lines:
                return
            chunk_text = "".join(current_lines)
            parse_search_replace_blocks(chunk_text)
            chunks.append(PlannedEdits(file_path=current_file, model_output=chunk_text))

        for line in model_text.splitlines(keepends=True):
            if line.strip().startswith("FILE:"):
                flush_current()
                rel_path = line.split("FILE:", 1)[1].strip()
                current_file = (self.workspace / rel_path).resolve()
                if not str(current_file).startswith(str(self.workspace.resolve())):
                    raise ValueError(f"Refusing edit outside workspace: {rel_path}")
                current_lines = []
                continue
            current_lines.append(line)

        flush_current()
        return chunks

    def _trigger_self_cleanup(self) -> None:
        self._running = False
        task = self._task
        self._task = None
        if task and not task.done():
            task.cancel()


class DevOpsEngineer(BaseActor):
    """Executes infrastructure tickets and provisions dynamic container environments."""

    def __init__(self, *, bus, memory: CorporateMemory, orchestrator: DockerOrchestrator | None = None) -> None:
        super().__init__(name="DevOpsEngineer", bus=bus, memory=memory)
        self._orchestrator = orchestrator or DockerOrchestrator()

    def register(self) -> None:
        self.bus.subscribe("ticket_created", self._enqueue)

    async def _enqueue(self, event: Event) -> None:
        ticket = Ticket.model_validate(event.payload)
        if ticket.role != "infra":
            return
        await self.inbox.put(ActorMessage(topic="infra_ticket", payload=ticket.model_dump(mode="json"), sender=event.sender))

    async def handle_message(self, message: ActorMessage) -> None:
        if message.topic != "infra_ticket":
            return

        ticket = Ticket.model_validate(message.payload)
        dockerfile = (
            "FROM python:3.11-slim\n"
            "WORKDIR /workspace\n"
            "RUN apt-get update && apt-get install -y --no-install-recommends curl git && rm -rf /var/lib/apt/lists/*\n"
            "RUN pip install --no-cache-dir pytest\n"
            "CMD [\"python\", \"--version\"]\n"
        )
        network_id = await asyncio.to_thread(self._orchestrator.create_network)
        image = await asyncio.to_thread(self._orchestrator.build_image, dockerfile)
        run_output = await asyncio.to_thread(self._orchestrator.run_container, image.tags[0], "python --version")

        ticket.status = "done"
        self.memory.upsert(ticket)
        await self.bus.publish(
            Event(
                topic="infra_ready",
                sender=self.name,
                payload={"ticket_id": ticket.id, "network_id": network_id, "image": image.tags[0], "output": run_output},
            )
        )
