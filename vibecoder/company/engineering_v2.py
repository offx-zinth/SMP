from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from google import genai

from vibecoder.agent.fuzzy_editor import EditFailedException, apply_edit_fuzzy, parse_search_replace_blocks
from vibecoder.company.event_bus import AsyncEventBus, Event
from vibecoder.company.leadership import ActorMessage, BaseActor
from vibecoder.company.persistent_shell import PersistentDockerShell
from vibecoder.company.state import CorporateMemory, PullRequest, SystemArchitecture, Ticket
from vibecoder.company.web_knowledge import KnowledgeEngine

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PlannedEdits:
    file_path: Path
    model_output: str


class DeveloperAgent(BaseActor):
    """Autonomous developer with research, pre-flight diagnostics, and escalation controls."""

    def __init__(
        self,
        *,
        name: str,
        role: str,
        bus: AsyncEventBus,
        memory: CorporateMemory,
        shell: PersistentDockerShell,
        knowledge: KnowledgeEngine,
        workspace: Path | None = None,
        gemini_api_key: str | None = None,
        max_attempts: int = 3,
    ) -> None:
        super().__init__(name=name, bus=bus, memory=memory)
        api_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise ValueError("DeveloperAgent requires GEMINI_API_KEY")

        self.role = role
        self.workspace = (workspace or Path.cwd()).resolve()
        self.shell = shell
        self.knowledge = knowledge
        self.max_attempts = max_attempts
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
        architecture = self._latest_architecture()
        last_error = ""
        changed_files: list[str] = []

        for attempt in range(1, self.max_attempts + 1):
            try:
                context = await self._plan_and_research(ticket=ticket, architecture=architecture, last_error=last_error)
                changed_files = await self._execute_edits(ticket=ticket, architecture=architecture, context=context)
                passed, output = await self._preflight_diagnostic(changed_files)
                if passed:
                    await self._open_pull_request(ticket=ticket, changed_files=changed_files)
                    ticket.status = "review"
                    self.memory.upsert(ticket)
                    return
                last_error = output
                logger.warning("Pre-flight failed for ticket=%s attempt=%s", ticket.id, attempt)
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                logger.exception("DeveloperAgent failed attempt=%s ticket=%s", attempt, ticket.id)

        ticket.status = "blocked"
        self.memory.upsert(ticket)
        await self.bus.publish(
            Event(
                topic="ticket_escalated",
                sender=self.name,
                payload={
                    "ticket_id": ticket.id,
                    "epic_id": ticket.epic_id,
                    "assignee": self.name,
                    "attempts": self.max_attempts,
                    "reason": "stuck in loop",
                    "last_error": last_error,
                },
            )
        )

    def _latest_architecture(self) -> SystemArchitecture | None:
        architectures = self.memory.list("system_architectures", limit=1)
        if not architectures:
            return None
        return SystemArchitecture.model_validate(architectures[0].model_dump())

    async def _plan_and_research(
        self,
        *,
        ticket: Ticket,
        architecture: SystemArchitecture | None,
        last_error: str,
    ) -> str:
        if not self._needs_research(ticket=ticket, last_error=last_error):
            return ""
        query = f"{ticket.title} {ticket.description} {last_error}".strip()
        return await self.knowledge.search_web(query[:500])

    async def _execute_edits(
        self,
        *,
        ticket: Ticket,
        architecture: SystemArchitecture | None,
        context: str,
    ) -> list[str]:
        prompt = self._build_prompt(ticket=ticket, architecture=architecture, research=context)
        response = await self._client.models.generate_content(model="gemini-3-pro", contents=prompt)
        model_text = (response.text or "").strip()
        if not model_text:
            raise RuntimeError("Gemini returned empty implementation response")

        edits = self._parse_file_scoped_blocks(model_text)
        changed_files: list[str] = []
        for edit in edits:
            if not edit.file_path.exists():
                raise FileNotFoundError(f"Model referenced missing file: {edit.file_path}")
            original = edit.file_path.read_text(encoding="utf-8")
            updated = original
            for block in parse_search_replace_blocks(edit.model_output):
                updated = apply_edit_fuzzy(updated, block.search, block.replace, threshold=0.85)
            if updated != original:
                edit.file_path.write_text(updated, encoding="utf-8")
                changed_files.append(str(edit.file_path.relative_to(self.workspace)))

        if not changed_files:
            raise EditFailedException("No file modifications were applied")
        return changed_files

    async def _preflight_diagnostic(self, changed_files: list[str]) -> tuple[bool, str]:
        command = self._select_preflight_command(changed_files)
        code, output = await self.shell.run_command(command, timeout_sec=180)
        return code == 0, output

    async def _open_pull_request(self, *, ticket: Ticket, changed_files: list[str]) -> None:
        pr = PullRequest(
            id=f"pr-{uuid.uuid4().hex[:8]}",
            ticket_id=ticket.id,
            title=f"[{self.role}] {ticket.title}",
            description=f"Autonomous implementation by {self.name}",
            branch=f"auto/{ticket.id}",
            files_changed=changed_files,
            checks={"preflight": "passed"},
        )
        self.memory.upsert(pr)
        await self.bus.publish(Event(topic="pull_request_opened", sender=self.name, payload=pr.model_dump(mode="json")))

    def _build_prompt(self, *, ticket: Ticket, architecture: SystemArchitecture | None, research: str) -> str:
        architecture_blob = architecture.model_dump_json(indent=2) if architecture else "{}"
        return (
            "You are a principal software engineer implementing a ticket. Return ONLY file-scoped SEARCH/REPLACE edits "
            "in this format:\n"
            "FILE: relative/path.py\n"
            "<<<<<<< SEARCH\n<exact snippet>\n=======\n<replacement snippet>\n>>>>>>> REPLACE\n\n"
            "No prose. Do not create new files.\n"
            f"Ticket: {ticket.model_dump_json(indent=2)}\n"
            f"Architecture: {architecture_blob}\n"
            f"Research: {research[:4000]}\n"
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
                target = (self.workspace / rel_path).resolve()
                if self.workspace not in target.parents and target != self.workspace:
                    raise ValueError(f"Refusing edit outside workspace: {rel_path}")
                current_file = target
                current_lines = []
                continue
            current_lines.append(line)

        flush_current()
        if not chunks:
            raise RuntimeError("No file-scoped edit chunks parsed from model output")
        return chunks

    @staticmethod
    def _needs_research(*, ticket: Ticket, last_error: str) -> bool:
        keywords = ("unknown", "deprecated", "api", "React 19", "docs", "hook", "typing")
        source = f"{ticket.description} {last_error}".lower()
        return any(keyword.lower() in source for keyword in keywords)

    @staticmethod
    def _select_preflight_command(changed_files: list[str]) -> str:
        python_changed = any(file.endswith(".py") for file in changed_files)
        ts_changed = any(file.endswith((".ts", ".tsx")) for file in changed_files)

        commands: list[str] = []
        if python_changed:
            commands.append("ruff check")
        if ts_changed:
            commands.append("npm run -s typecheck || npx tsc --noEmit")
        if not commands:
            commands.append("echo 'No preflight linter for changed file types'")
        return " && ".join(commands)


def summarize_escalation(payload: dict[str, object]) -> str:
    return json.dumps(
        {
            "ticket_id": payload.get("ticket_id"),
            "attempts": payload.get("attempts"),
            "reason": payload.get("reason"),
            "last_error": payload.get("last_error"),
        },
        indent=2,
    )


__all__ = ["DeveloperAgent", "summarize_escalation"]
