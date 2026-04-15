"""Sandbox spawner for creating isolated execution environments.

Manages the lifecycle of sandboxed processes and containers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from smp.logging import get_logger

log = get_logger(__name__)

_DEFAULT_SANDBOX_ROOT = Path.home() / ".smp" / "sandboxes"


@dataclass
class SandboxInfo:
    """Information about a spawned sandbox."""

    sandbox_id: str
    root_path: str
    created_at: str
    status: str = "created"
    pid: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SandboxSpawner:
    """Spawns and manages isolated sandbox directories."""

    def __init__(self, sandbox_root: Path | None = None) -> None:
        self._root = sandbox_root or _DEFAULT_SANDBOX_ROOT
        self._sandboxes: dict[str, SandboxInfo] = {}

    def spawn(
        self,
        name: str | None = None,
        template: str | None = None,
        files: dict[str, str] | None = None,
    ) -> SandboxInfo:
        """Create a new sandbox directory."""
        sandbox_id = f"sandbox_{uuid.uuid4().hex[:8]}"
        sandbox_name = name or sandbox_id
        sandbox_path = self._root / sandbox_name

        sandbox_path.mkdir(parents=True, exist_ok=True)

        if template:
            template_path = self._root / template
            if template_path.exists():
                import shutil

                shutil.copytree(template_path, sandbox_path, dirs_exist_ok=True)

        if files:
            for rel_path, content in files.items():
                file_path = sandbox_path / rel_path
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content, encoding="utf-8")

        info = SandboxInfo(
            sandbox_id=sandbox_id,
            root_path=str(sandbox_path),
            created_at=datetime.now(UTC).isoformat(),
        )
        self._sandboxes[sandbox_id] = info

        log.info("sandbox_spawned", sandbox_id=sandbox_id, path=str(sandbox_path))
        return info

    def get(self, sandbox_id: str) -> SandboxInfo | None:
        """Get sandbox info by ID."""
        return self._sandboxes.get(sandbox_id)

    def list_active(self) -> list[SandboxInfo]:
        """List all active sandboxes."""
        return list(self._sandboxes.values())

    def destroy(self, sandbox_id: str) -> bool:
        """Remove a sandbox directory."""
        info = self._sandboxes.get(sandbox_id)
        if not info:
            return False

        import shutil

        path = Path(info.root_path)
        if path.exists():
            shutil.rmtree(path)

        del self._sandboxes[sandbox_id]
        log.info("sandbox_destroyed", sandbox_id=sandbox_id)
        return True

    async def cleanup_all(self) -> int:
        """Remove all sandbox directories."""
        import shutil

        count = 0
        for sandbox_id, info in list(self._sandboxes.items()):
            path = Path(info.root_path)
            if path.exists():
                shutil.rmtree(path)
                count += 1
            del self._sandboxes[sandbox_id]

        log.info("sandboxes_cleaned", count=count)
        return count
