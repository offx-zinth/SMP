from __future__ import annotations

import asyncio
import contextlib
import logging
import select
import shlex
import time
from dataclasses import dataclass
from typing import Final

import docker
from docker.errors import DockerException, NotFound
from docker.models.containers import Container

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CommandResult:
    exit_code: int
    output: str


class PersistentDockerShell:
    """Maintains a long-lived interactive bash session in an existing Docker container."""

    _READ_CHUNK: Final[int] = 4096

    def __init__(
        self,
        *,
        container_name: str | None = None,
        container_id: str | None = None,
        workspace_dir: str = "/workspace",
        shell: str = "bash",
    ) -> None:
        if not container_name and not container_id:
            raise ValueError("container_name or container_id is required")
        self._client = docker.from_env()
        self._container_ref = container_id or container_name or ""
        self._workspace_dir = workspace_dir
        self._shell = shell
        self._container: Container | None = None
        self._exec_socket: object | None = None
        self._exec_id: str | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "PersistentDockerShell":
        await self._ensure_session()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        async with self._lock:
            if self._exec_socket is None:
                return
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self._exec_socket.close)
            self._exec_socket = None
            self._exec_id = None

    async def run_command(self, command: str, timeout_sec: int = 120) -> tuple[int, str]:
        """Execute command in persistent shell and return (exit_code, merged_output)."""
        stripped = command.strip()
        if not stripped:
            return 0, ""

        async with self._lock:
            await self._ensure_session()
            normalized = self._normalize_command(stripped)
            marker = f"__VIBECODER_EXIT_{int(time.time() * 1000)}__"
            payload = f"{normalized}\necho {marker}$?\n"
            await asyncio.to_thread(self._send, payload.encode("utf-8", errors="ignore"))
            output, exit_code = await asyncio.wait_for(
                asyncio.to_thread(self._read_until_marker, marker),
                timeout=timeout_sec,
            )
            return exit_code, output

    async def _ensure_session(self) -> None:
        if self._exec_socket is not None:
            return
        self._container = await asyncio.to_thread(self._resolve_container)
        api = self._client.api
        try:
            self._exec_id = await asyncio.to_thread(
                api.exec_create,
                self._container.id,
                cmd=[self._shell, "-i"],
                tty=True,
                stdin=True,
                environment={"TERM": "xterm-256color"},
                workdir=self._workspace_dir,
            )
            self._exec_socket = await asyncio.to_thread(
                api.exec_start,
                self._exec_id,
                tty=True,
                stream=False,
                socket=True,
            )
        except DockerException as exc:
            raise RuntimeError(f"Unable to attach persistent shell: {exc}") from exc
        await asyncio.sleep(0.1)

    def _resolve_container(self) -> Container:
        try:
            container = self._client.containers.get(self._container_ref)
        except NotFound as exc:
            raise RuntimeError(f"Container not found: {self._container_ref}") from exc
        if container.status != "running":
            container.reload()
            if container.status != "running":
                raise RuntimeError(f"Container {self._container_ref} is not running")
        return container

    def _send(self, data: bytes) -> None:
        if self._exec_socket is None:
            raise RuntimeError("Persistent shell socket not initialized")
        self._exec_socket.send(data)

    def _read_until_marker(self, marker: str) -> tuple[str, int]:
        if self._exec_socket is None:
            raise RuntimeError("Persistent shell socket not initialized")

        chunks: list[str] = []
        marker_value: int | None = None
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self._exec_socket], [], [], 0.2)
            if not ready:
                continue
            data = self._exec_socket.recv(self._READ_CHUNK)
            if not data:
                break
            text = data.decode("utf-8", errors="replace")
            chunks.append(text)
            merged = "".join(chunks)
            if marker in merged:
                output, _, rest = merged.partition(marker)
                exit_digits = []
                for ch in rest:
                    if ch.isdigit():
                        exit_digits.append(ch)
                    elif exit_digits:
                        break
                marker_value = int("".join(exit_digits) or "0")
                clean = output.replace("\r", "")
                return clean, marker_value

        raise TimeoutError("Persistent shell did not return completion marker in time")

    def _normalize_command(self, command: str) -> str:
        if self._should_background(command):
            log_file = f"/tmp/vibecoder-bg-{int(time.time())}.log"
            quoted = shlex.quote(command)
            return (
                f"nohup bash -lc {quoted} > {shlex.quote(log_file)} 2>&1 & "
                "echo '[background-process-started pid='$!' log="
                f"{log_file}]'"
            )
        return command

    @staticmethod
    def _should_background(command: str) -> bool:
        if command.endswith("&") or "nohup" in command:
            return False
        if any(op in command for op in ["&&", "||", ";", "|", "\n"]):
            return False
        long_running_prefixes = (
            "npm run dev",
            "npm start",
            "pnpm dev",
            "yarn dev",
            "uvicorn",
            "next dev",
            "python -m http.server",
        )
        return command.startswith(long_running_prefixes)


__all__ = ["PersistentDockerShell", "CommandResult"]
