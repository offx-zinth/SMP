from __future__ import annotations

import asyncio
import contextlib
import logging
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import docker
    from docker.errors import DockerException, NotFound
    from docker.models.containers import Container
except Exception:  # noqa: BLE001
    docker = None
    DockerException = RuntimeError
    NotFound = RuntimeError
    Container = Any


@dataclass(slots=True, frozen=True)
class CommandResult:
    command: str
    exit_code: int
    output: str


class DockerWorkspace:
    """Ephemeral Docker execution workspace for isolated command execution."""

    def __init__(
        self,
        workspace_dir: Path,
        *,
        image: str = "python:3.11-slim",
        name_prefix: str = "vibecoder-sandbox",
    ) -> None:
        if docker is None:
            raise RuntimeError("docker package is not installed; cannot create DockerWorkspace")

        self._workspace_dir = workspace_dir.resolve()
        self._image = image
        self._name_prefix = name_prefix
        self._client = docker.from_env()
        self._container: Container | None = None
        self._lock = asyncio.Lock()

    @property
    def active_container_id(self) -> str | None:
        return self._container.id if self._container else None

    async def start(self) -> None:
        await asyncio.to_thread(self._start_sync)

    def _start_sync(self) -> None:
        if self._container is not None:
            return

        logger.info("Starting Docker sandbox image=%s", self._image)
        self._client.images.pull(self._image)
        self._container = self._client.containers.run(
            self._image,
            command="sleep infinity",
            detach=True,
            tty=True,
            working_dir="/workspace",
            volumes={str(self._workspace_dir): {"bind": "/workspace", "mode": "rw"}},
            name=f"{self._name_prefix}-{id(self)}",
        )

    async def execute(self, command: str, *, timeout_seconds: int = 300) -> CommandResult:
        """Execute a shell command inside the sandboxed container."""
        if not command.strip():
            raise ValueError("command cannot be empty")
        if self._container is None:
            raise RuntimeError("Sandbox has not been started")

        async with self._lock:
            try:
                return await asyncio.wait_for(asyncio.to_thread(self._exec_sync, command), timeout=timeout_seconds)
            except asyncio.TimeoutError as exc:
                raise TimeoutError(f"Command timed out after {timeout_seconds}s: {command}") from exc

    def _exec_sync(self, command: str) -> CommandResult:
        if self._container is None:
            raise RuntimeError("Sandbox is unavailable")

        safe_cmd = f"/bin/sh -lc {shlex.quote(command)}"
        exec_result = self._container.exec_run(safe_cmd, stdout=True, stderr=True, demux=False)
        output = exec_result.output.decode("utf-8", errors="replace") if isinstance(exec_result.output, bytes) else str(exec_result.output)
        return CommandResult(command=command, exit_code=int(exec_result.exit_code), output=output[-8000:])

    async def stop(self) -> None:
        await asyncio.to_thread(self._stop_sync)

    def _stop_sync(self) -> None:
        if self._container is None:
            return

        with contextlib.suppress(DockerException, NotFound):
            self._container.remove(force=True)
        self._container = None

    async def __aenter__(self) -> "DockerWorkspace":
        await self.start()
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: Any) -> None:
        await self.stop()
