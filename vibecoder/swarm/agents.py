from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Literal

from google import genai
from pydantic import BaseModel, Field, ValidationError

from vibecoder.context import AppContext
from vibecoder.smp.memory import SMPMemory
from vibecoder.swarm.tools_swarm import SwarmTools


class Task(BaseModel):
    id: str
    description: str
    target_files: list[str] = Field(default_factory=list)
    verification_cmd: str = "python -m compileall vibecoder"


class TaskPlan(BaseModel):
    intent: str
    reasoning: str
    tasks: list[Task]


class WorkerAction(BaseModel):
    action: Literal["read_file", "explore_graph", "edit_and_verify", "finish"]
    reasoning: str
    args: dict[str, Any] = Field(default_factory=dict)


class WorkerResult(BaseModel):
    task_id: str
    success: bool
    summary: str
    iterations: int
    logs: list[str] = Field(default_factory=list)


class WorkerAgent:
    """Async ReAct worker that repeatedly plans tool calls until task completion."""

    def __init__(
        self,
        app_context: AppContext,
        memory: SMPMemory,
        task: Task,
        *,
        max_iterations: int = 8,
    ) -> None:
        self.context = app_context
        self.memory = memory
        self.task = task
        self.max_iterations = max_iterations
        self.client = genai.Client(api_key=app_context.config.gemini_api_key).aio
        self.tools = SwarmTools(app_context.config.workspace_dir.resolve(), memory)

    async def run(self, *, model: str = "gemini-2.5-pro") -> WorkerResult:
        scratchpad = ""
        logs: list[str] = []

        for iteration in range(1, self.max_iterations + 1):
            action = await self._next_action(model=model, scratchpad=scratchpad)
            if action.action == "finish":
                return WorkerResult(
                    task_id=self.task.id,
                    success=True,
                    summary=action.args.get("summary", action.reasoning),
                    iterations=iteration,
                    logs=logs,
                )

            try:
                observation = await self._execute_action(action)
            except Exception as exc:  # noqa: BLE001
                observation = f"Tool failure: {exc}"

            step_log = (
                f"iter={iteration} action={action.action} reasoning={action.reasoning}\n"
                f"args={json.dumps(action.args, ensure_ascii=False)}\n"
                f"observation={observation[:1200]}"
            )
            logs.append(step_log)
            scratchpad += f"\n{step_log}\n"

        return WorkerResult(
            task_id=self.task.id,
            success=False,
            summary="Maximum iterations reached before satisfying task objective.",
            iterations=self.max_iterations,
            logs=logs,
        )

    async def _next_action(self, *, model: str, scratchpad: str) -> WorkerAction:
        prompt = (
            "You are a software-engineering worker agent in a multi-agent swarm. "
            "Given the task, choose one next action in JSON.\n"
            "Allowed actions: read_file, explore_graph, edit_and_verify, finish.\n"
            "For edit_and_verify include filepath, search_block, replace_block, verification_cmd.\n"
            "If verification fails, use returned stderr to self-heal in the next step.\n"
            "Respond with strict JSON matching: {action, reasoning, args}.\n\n"
            f"Task: {self.task.model_dump_json()}\n"
            f"Scratchpad:\n{scratchpad[-6000:]}"
        )
        response = await self.client.models.generate_content(model=model, contents=prompt)
        payload = self._extract_json(response.text or "")
        try:
            return WorkerAction.model_validate(payload)
        except ValidationError:
            return WorkerAction(action="finish", reasoning="Model returned invalid action payload.", args={"summary": "No-op."})

    async def _execute_action(self, action: WorkerAction) -> str:
        if action.action == "read_file":
            return await self.tools.read_file(**action.args)
        if action.action == "explore_graph":
            return await self.tools.explore_graph(**action.args)
        if action.action == "edit_and_verify":
            args = dict(action.args)
            args.setdefault("verification_cmd", self.task.verification_cmd)
            return await self.tools.edit_and_verify(**args)
        return "Action completed."

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        stripped = text.strip()
        if not stripped:
            return {}
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            start = stripped.find("{")
            end = stripped.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(stripped[start : end + 1])
                except json.JSONDecodeError:
                    return {}
        return {}


class OrchestratorAgent:
    """Parent planner that builds a task plan and executes workers concurrently."""

    def __init__(self, app_context: AppContext, memory: SMPMemory | None = None) -> None:
        self.context = app_context
        self.memory = memory or SMPMemory(app_context)
        self.client = genai.Client(api_key=app_context.config.gemini_api_key).aio

    async def run(self, intent: str, *, model: str = "gemini-2.5-pro") -> tuple[TaskPlan, list[WorkerResult]]:
        plan = await self._build_plan(intent=intent, model=model)
        workers = [WorkerAgent(self.context, self.memory, task) for task in plan.tasks]
        results = await asyncio.gather(*(worker.run(model=model) for worker in workers), return_exceptions=True)

        normalized: list[WorkerResult] = []
        for task, result in zip(plan.tasks, results, strict=False):
            if isinstance(result, WorkerResult):
                normalized.append(result)
            else:
                normalized.append(
                    WorkerResult(
                        task_id=task.id,
                        success=False,
                        summary=f"Worker crashed: {result}",
                        iterations=0,
                    )
                )
        return plan, normalized

    async def _build_plan(self, *, intent: str, model: str) -> TaskPlan:
        blast_radius = await asyncio.to_thread(self._collect_blast_radius_context)
        prompt = (
            "You are the Orchestrator in a coding swarm. Create a high-quality execution plan "
            "as strict JSON with keys: intent, reasoning, tasks. Each task requires id, description, "
            "target_files, verification_cmd. Keep tasks independent for parallel execution.\n\n"
            f"User intent: {intent}\n"
            f"SMP blast-radius context:\n{blast_radius[:12000]}"
        )
        response = await self.client.models.generate_content(model=model, contents=prompt)
        payload = WorkerAgent._extract_json(response.text or "")

        try:
            return TaskPlan.model_validate(payload)
        except ValidationError:
            fallback = Task(
                id="task-1",
                description=intent,
                target_files=self._candidate_files(limit=3),
            )
            return TaskPlan(intent=intent, reasoning="Fallback single-task plan due to parse failure.", tasks=[fallback])

    def _collect_blast_radius_context(self) -> str:
        contexts: list[str] = []
        for file_path in self._candidate_files(limit=5):
            try:
                contexts.append(self.memory.get_compressed_context(file_path))
            except Exception:  # noqa: BLE001
                continue
        return "\n\n".join(contexts) if contexts else "{}"

    def _candidate_files(self, *, limit: int) -> list[str]:
        files: list[str] = []
        workspace = self.context.config.workspace_dir.resolve()
        for _, attrs in self.memory.graph.nodes(data=True):
            if attrs.get("type") != "file":
                continue
            raw_path = attrs.get("file_path")
            if not raw_path:
                continue
            try:
                rel = str(Path(str(raw_path)).resolve().relative_to(workspace))
            except ValueError:
                rel = str(raw_path)
            files.append(rel)
            if len(files) >= limit:
                break
        return files
