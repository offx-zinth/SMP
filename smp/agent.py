"""CodingAgent — AI coding agent powered by Structural Memory Protocol.

Wraps :class:`SMPClient` into a six-step workflow that gathers structural
context, assesses change impact, asks an LLM to generate an edit, writes
the result to disk, and syncs the graph back.

Usage::

    from smp.agent import CodingAgent
    from smp.client import SMPClient

    async with SMPClient("http://localhost:8420") as client:
        agent = CodingAgent(client, zen_api_key="...")
        result = await agent.run(
            file_path="src/auth.py",
            instruction="Add rate limiting to the login endpoint",
        )
        print(result["summary"])
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

import msgspec

from smp.client import SMPClient
from smp.logging import get_logger

log = get_logger(__name__)


class AgentError(Exception):
    """Raised when the agent cannot complete its workflow."""


class AgentResult(msgspec.Struct):
    """Outcome of a single :meth:`CodingAgent.run` invocation."""

    file_path: str
    instruction: str
    original_content: str
    edited_content: str
    context: dict[str, Any] = msgspec.field(default_factory=dict)
    impact: dict[str, Any] = msgspec.field(default_factory=dict)
    summary: str = ""
    nodes_synced: int = 0
    edges_synced: int = 0


# ---------------------------------------------------------------------------
# Gemini LLM backend (lazy import, mirrors enricher pattern)
# ---------------------------------------------------------------------------


class _GeminiBackend:
    """Wraps Google Gemini API for code-edit generation using Gemma 3."""

    def __init__(self, api_key: str, model: str = "gemma-3-27b-it") -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Generate a response from the model."""
        response = self._client.models.generate_content(
            model=self._model,
            contents=f"{system_prompt}\n\n{user_prompt}",
        )
        return str(response.text or "")


# ---------------------------------------------------------------------------
# CodingAgent
# ---------------------------------------------------------------------------


class CodingAgent:
    """AI coding agent that uses SMP for structural awareness.

    The agent follows a six-step workflow:

    1. **Context** — query ``smp/context`` for the file's mental model.
    2. **Impact** — query ``smp/impact`` for blast-radius analysis.
    3. **Generate** — send context + instruction to the LLM for an edit.
    4. **Write** — persist the edited file to disk.
    5. **Sync** — call ``smp/update`` so SMP re-parses the changed file.

    Args:
        client: Connected :class:`SMPClient` instance.
        gemini_api_key: Google Gemini API key. Falls back to GEMINI_API_KEY or GOOGLE_API_KEY env var.
        model: Gemini model name (default: gemma-3-27b-it).
    """

    def __init__(
        self,
        client: SMPClient,
        *,
        gemini_api_key: str | None = None,
        model: str = "gemma-3-27b-it",
    ) -> None:
        self._client = client
        self._llm: _GeminiBackend | None = None

        key = gemini_api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if key:
            try:
                self._llm = _GeminiBackend(api_key=key, model=model)
                log.info("agent_llm_ready", model=model)
            except Exception as exc:
                log.warning("agent_llm_init_failed", error=str(exc))
        else:
            log.warning("agent_no_llm", reason="no_api_key")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, file_path: str, instruction: str) -> AgentResult:
        """Execute the full agent workflow and return the result.

        Args:
            file_path: Path to the source file to edit.
            instruction: Natural-language description of the desired change.

        Returns:
            An :class:`AgentResult` with before/after content and metadata.

        Raises:
            AgentError: On unrecoverable failures (missing file, no LLM, etc.).
        """
        workflow_id = f"wf_{int(time.monotonic() * 1000)}"
        log.info(
            "agent_workflow_start",
            workflow_id=workflow_id,
            file_path=file_path,
            instruction=instruction[:120],
        )

        t_start = time.monotonic()

        # Step 1 — read the current file
        original = await self._read_file(file_path)
        log.info("agent_step_complete", step=1, label="read_file", workflow_id=workflow_id)

        # Step 2 — structural context
        context = await self._step_context(file_path, workflow_id)

        # Step 3 — impact assessment
        impact = await self._step_impact(file_path, context, workflow_id)

        # Step 4 — LLM edit generation
        edited = await self._step_generate(file_path, instruction, original, context, impact, workflow_id)

        # Step 5 — write to disk
        await self._step_write(file_path, edited, workflow_id)

        # Step 6 — sync back into structural memory
        sync_result = await self._step_sync(file_path, edited, workflow_id)

        elapsed = round(time.monotonic() - t_start, 2)
        nodes = sync_result.get("nodes", 0)
        edges = sync_result.get("edges", 0)

        summary = f"Edited {file_path}: {instruction}. Synced {nodes} nodes, {edges} edges in {elapsed}s."

        log.info(
            "agent_workflow_complete",
            workflow_id=workflow_id,
            file_path=file_path,
            elapsed_s=elapsed,
            nodes=nodes,
            edges=edges,
        )

        return AgentResult(
            file_path=file_path,
            instruction=instruction,
            original_content=original,
            edited_content=edited,
            context=context,
            impact=impact,
            summary=summary,
            nodes_synced=nodes,
            edges_synced=edges,
        )

    # ------------------------------------------------------------------
    # Step implementations
    # ------------------------------------------------------------------

    async def _read_file(self, file_path: str) -> str:
        """Read file content from disk."""
        log.info("agent_read_file", file_path=file_path)
        path = Path(file_path)
        if not path.exists():
            raise AgentError(f"File not found: {file_path}")
        content = path.read_text(encoding="utf-8")
        log.info("agent_file_read", file_path=file_path, size_bytes=len(content))
        return content

    async def _step_context(self, file_path: str, workflow_id: str) -> dict[str, Any]:
        """Step 2 — query SMP for the file's structural context."""
        log.info("agent_step_start", step=2, label="context", workflow_id=workflow_id)

        ctx = await self._client.get_context(file_path, scope="edit", include_semantic=True)

        node_count = len(ctx.get("nodes", []))
        edge_count = len(ctx.get("edges", []))
        types = self._summarise_node_types(ctx.get("nodes", []))

        log.info(
            "agent_context_ready",
            workflow_id=workflow_id,
            nodes=node_count,
            edges=edge_count,
            **types,
        )
        return ctx

    async def _step_impact(
        self,
        file_path: str,
        context: dict[str, Any],
        workflow_id: str,
    ) -> dict[str, Any]:
        """Step 3 — assess the blast radius of modifying *file_path*."""
        log.info("agent_step_start", step=3, label="impact", workflow_id=workflow_id)

        nodes = context.get("nodes", [])
        target_id = self._pick_impact_target(nodes, file_path)

        if not target_id:
            log.info("agent_impact_skip", workflow_id=workflow_id, reason="no_entity_found")
            return {"entity": None, "affected_nodes": [], "total_affected": 0}

        impact = await self._client.assess_impact(target_id, depth=10)
        affected = impact.get("affected_nodes", [])

        # Build a concise summary of downstream effects
        downstream = self._format_downstream(affected)

        log.info(
            "agent_impact_assessed",
            workflow_id=workflow_id,
            entity=target_id,
            affected_count=len(affected),
            downstream=downstream[:8],
        )
        return impact

    async def _step_generate(
        self,
        file_path: str,
        instruction: str,
        original: str,
        context: dict[str, Any],
        impact: dict[str, Any],
        workflow_id: str,
    ) -> str:
        """Step 4 — ask the LLM to produce an edited version of the file."""
        log.info("agent_step_start", step=4, label="generate", workflow_id=workflow_id)

        if not self._llm:
            raise AgentError("No LLM backend available. Set ZEN_API_KEY to enable edit generation.")

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            file_path=file_path,
            instruction=instruction,
            original=original,
            context=context,
            impact=impact,
        )

        log.info("agent_llm_call", workflow_id=workflow_id, model=self._llm._model)
        raw = self._llm.generate(system_prompt, user_prompt)
        edited = self._extract_code(raw)

        log.info(
            "agent_llm_response",
            workflow_id=workflow_id,
            raw_chars=len(raw),
            edited_chars=len(edited),
        )
        return edited

    async def _step_write(self, file_path: str, content: str, workflow_id: str) -> None:
        """Step 5 — write the edited content to disk."""
        log.info("agent_step_start", step=5, label="write", workflow_id=workflow_id)

        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

        log.info("agent_file_written", file_path=file_path, size_bytes=len(content))

    async def _step_sync(self, file_path: str, content: str, workflow_id: str) -> dict[str, Any]:
        """Step 6 — push the changed file back into the structural memory."""
        log.info("agent_step_start", step=6, label="sync", workflow_id=workflow_id)

        result = await self._client.update(file_path, content=content)

        log.info(
            "agent_sync_complete",
            workflow_id=workflow_id,
            file_path=file_path,
            nodes=result.get("nodes", 0),
            edges=result.get("edges", 0),
            enriched=result.get("enriched", 0),
            errors=result.get("errors", 0),
        )
        return result

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_system_prompt() -> str:
        return (
            "You are an expert software engineer. You will receive a source file, "
            "its structural context (classes, functions, imports, relationships), "
            "and an instruction for how to modify it.\n\n"
            "Rules:\n"
            "- Return ONLY the complete modified file content.\n"
            "- Do NOT wrap in markdown code fences.\n"
            "- Do NOT add explanations before or after the code.\n"
            "- Preserve existing style, conventions, and imports.\n"
            "- Only change what the instruction requires.\n"
            "- Ensure the result is syntactically valid."
        )

    @staticmethod
    def _build_user_prompt(
        *,
        file_path: str,
        instruction: str,
        original: str,
        context: dict[str, Any],
        impact: dict[str, Any],
    ) -> str:
        parts: list[str] = []

        parts.append(f"## File: {file_path}")
        parts.append(f"## Instruction\n{instruction}")

        # Context block
        nodes = context.get("nodes", [])
        edges = context.get("edges", [])
        if nodes:
            parts.append("## Structural Context")
            for n in nodes[:30]:
                sem = n.get("semantic")
                purpose = f" — {sem['purpose']}" if sem and sem.get("purpose") else ""
                parts.append(f"  - {n['type']} {n['name']} (L{n['start_line']}-{n['end_line']}){purpose}")
            if edges:
                parts.append(f"  ({len(edges)} relationships)")

        # Impact block
        affected = impact.get("affected_nodes", [])
        if affected:
            parts.append(f"## Impact Analysis — {len(affected)} downstream entities affected")
            for a in affected[:10]:
                parts.append(f"  - {a['type']} {a['name']} in {a['file_path']}")
            if len(affected) > 10:
                parts.append(f"  ... and {len(affected) - 10} more")

        # Original source
        parts.append(f"## Current Source\n```\n{original}\n```")
        parts.append("## Modified Source")

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_code(llm_response: str) -> str:
        """Extract source code from an LLM response.

        Handles responses wrapped in markdown code fences as well as raw code.
        """
        fenced: list[str] = re.findall(r"```(?:\w*)\n(.*?)```", llm_response, re.DOTALL)
        if fenced:
            return str(fenced[0].strip())
        # No fences — strip common LLM preamble lines
        lines = llm_response.split("\n")
        start = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith("//"):
                start = i
                break
        return "\n".join(lines[start:]).strip()

    @staticmethod
    def _summarise_node_types(nodes: list[dict[str, Any]]) -> dict[str, int]:
        """Count nodes by type for structured log output."""
        counts: dict[str, int] = {}
        for n in nodes:
            t = n.get("type", "UNKNOWN")
            counts[t] = counts.get(t, 0) + 1
        return counts

    @staticmethod
    def _pick_impact_target(nodes: list[dict[str, Any]], file_path: str) -> str | None:
        """Choose the best entity for impact analysis.

        Prefers the first FUNCTION or CLASS node; falls back to the FILE node.
        """
        file_node_id: str | None = None
        for n in nodes:
            ntype = str(n.get("type", ""))
            nid = str(n.get("id", ""))
            if ntype in ("FUNCTION", "CLASS"):
                return nid
            if ntype == "FILE" and not file_node_id:
                file_node_id = nid
        return file_node_id

    @staticmethod
    def _format_downstream(affected: list[dict[str, Any]]) -> list[str]:
        """Format affected nodes into compact summary strings."""
        return [f"{a.get('type', '?')} {a.get('name', '?')} @ {a.get('file_path', '?')}" for a in affected]
