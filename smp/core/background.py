from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class BackgroundProcess:
    name: str
    command: list[str]
    pid: int
    cwd: Path | None = None
    env: dict[str, str] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)


class BackgroundRunner:
    """Manages long-running background processes without blocking the agent."""

    def __init__(self) -> None:
        self._base_dir = Path.home() / ".smp" / "runs"
        self._processes: dict[str, BackgroundProcess] = {}
        self._open_files: dict[str, tuple[Any, Any]] = {}
        self._load()

    def _state_file(self) -> Path:
        return self._base_dir / "state.json"

    def _load(self) -> None:
        f = self._state_file()
        if f.exists():
            with open(f) as fp:
                data = json.load(fp)
            for name, item in data.items():
                proc = BackgroundProcess(
                    name=name,
                    command=item["command"],
                    pid=item["pid"],
                    cwd=Path(item["cwd"]) if item.get("cwd") else None,
                    env=item.get("env", {}),
                    started_at=item.get("started_at", 0),
                )
                if self._is_running(proc.pid):
                    self._processes[name] = proc

    def _save(self) -> None:
        self._base_dir.mkdir(parents=True, exist_ok=True)
        data = {
            name: {
                "command": proc.command,
                "pid": proc.pid,
                "cwd": str(proc.cwd) if proc.cwd else None,
                "env": proc.env,
                "started_at": proc.started_at,
            }
            for name, proc in self._processes.items()
        }
        with open(self._state_file(), "w") as fp:
            json.dump(data, fp)

    def start(
        self,
        name: str,
        command: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> BackgroundProcess:
        """Start a command in background and return immediately."""
        if name in self._processes:
            raise ValueError(f"Process already running: {name}")

        self._base_dir.mkdir(parents=True, exist_ok=True)
        run_dir = self._base_dir / name
        run_dir.mkdir(parents=True, exist_ok=True)

        full_env = os.environ.copy()
        if env:
            full_env.update(env)

        with open(run_dir / "stdout.log", "wb") as stdout_file, open(run_dir / "stderr.log", "wb") as stderr_file:
            proc = subprocess.Popen(
                command,
                stdout=stdout_file,
                stderr=stderr_file,
                cwd=cwd or run_dir,
                env=full_env,
                start_new_session=True,
                text=True,
            )

            self._open_files[name] = (None, None)  # Files closed after Popen

        bg_proc = BackgroundProcess(
            name=name,
            command=command,
            pid=proc.pid,
            cwd=cwd,
            env=env,
        )
        self._processes[name] = bg_proc
        self._save()
        return bg_proc

    def stop(self, name: str) -> bool:
        """Stop a running process by name."""
        if name not in self._processes:
            return False

        bg_proc = self._processes[name]
        with contextlib.suppress(ProcessLookupError):
            os.kill(bg_proc.pid, signal.SIGTERM)

        self._open_files.pop(name, None)

        del self._processes[name]
        self._save()
        return True

    def restart(self, name: str) -> BackgroundProcess:
        """Restart a stopped or existing process."""
        if name not in self._processes:
            raise ValueError(f"Unknown process: {name}")

        bg_proc = self._processes[name]
        self.stop(name)
        return self.start(name, bg_proc.command, bg_proc.cwd, bg_proc.env)

    def list(self) -> dict[str, dict[str, Any]]:
        """List all managed processes."""
        result = {}
        for name, proc in self._processes.items():
            result[name] = {
                "pid": proc.pid,
                "command": proc.command,
                "cwd": str(proc.cwd) if proc.cwd else None,
                "running": self._is_running(proc.pid),
            }
        return result

    def get(self, name: str) -> dict[str, Any] | None:
        """Get details of a specific process."""
        if name not in self._processes:
            return None

        proc = self._processes[name]
        return {
            "pid": proc.pid,
            "command": proc.command,
            "cwd": str(proc.cwd) if proc.cwd else None,
            "running": self._is_running(proc.pid),
        }

    def logs(self, name: str) -> dict[str, str]:
        """Get stdout/stderr log contents for a process."""
        if name not in self._processes and not (self._base_dir / name).exists():
            raise ValueError(f"Unknown process: {name}")

        run_dir = self._base_dir / name
        stdout = ""
        stderr = ""
        if (run_dir / "stdout.log").exists():
            with open(run_dir / "stdout.log") as fp:
                stdout = fp.read()
        if (run_dir / "stderr.log").exists():
            with open(run_dir / "stderr.log") as fp:
                stderr = fp.read()
        return {"stdout": stdout, "stderr": stderr}

    def _is_running(self, pid: int) -> bool:
        """Check if a process is still running."""
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
