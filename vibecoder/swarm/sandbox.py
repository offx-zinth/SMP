from __future__ import annotations

import asyncio
from pathlib import Path

_OUTPUT_TAIL_CHARS = 2_000


async def run_command(command: str, timeout: int = 30) -> dict[str, int | str]:
    """Execute a shell command in the current workspace with bounded output."""
    workspace = Path.cwd()
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=str(workspace),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
        exit_code = process.returncode if process.returncode is not None else 1
    except asyncio.TimeoutError:
        process.kill()
        stdout_bytes, stderr_bytes = await process.communicate()
        timed_out_message = f"Command timed out after {timeout}s: {command}"
        stderr_bytes = (stderr_bytes.decode("utf-8", errors="replace") + "\n" + timed_out_message).encode(
            "utf-8", errors="replace"
        )
        exit_code = 124

    stdout = stdout_bytes.decode("utf-8", errors="replace")[-_OUTPUT_TAIL_CHARS:]
    stderr = stderr_bytes.decode("utf-8", errors="replace")[-_OUTPUT_TAIL_CHARS:]
    return {"exit_code": exit_code, "stdout": stdout, "stderr": stderr}
