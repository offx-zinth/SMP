"""End-to-end tests for the MCP server over stdio (real subprocess, real client)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from smp.cli import ingest_directory


@pytest.fixture()
async def mcp_graph(tmp_path: Path) -> Path:
    """Ingest a small multi-language project for MCP queries."""
    project = tmp_path / "langproj"
    project.mkdir()
    (project / "app.py").write_text("def compute(x):\n    return validate(x)\n\ndef validate(x):\n    return x\n")
    (project / "handler.js").write_text("function handle(req) {\n    return compute(req);\n}\n")
    graph_path = tmp_path / "mcp.smpg"
    await ingest_directory(str(project), graph_path=str(graph_path), clear=True)
    return graph_path


def _server_params(graph_path: Path) -> StdioServerParameters:
    env = dict(os.environ)
    env["SMP_GRAPH_PATH"] = str(graph_path)
    env["SMP_OPEN_MODE"] = "1"
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "smp.cli", "mcp", "--graph-path", str(graph_path)],
        env=env,
        cwd=str(Path.cwd()),
    )


@pytest.mark.asyncio
async def test_mcp_lists_all_tools(mcp_graph: Path) -> None:
    """The MCP server exposes every RPC method as a tool."""
    from smp.protocol.server import _HANDLERS

    async with stdio_client(_server_params(mcp_graph)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
    names = {t.name for t in tools.tools}
    for method in _HANDLERS:
        assert method.replace("/", "_") in names, f"missing MCP tool for {method}"


@pytest.mark.asyncio
async def test_mcp_navigate_end_to_end(mcp_graph: Path) -> None:
    """An agent can navigate the graph through the MCP tool."""
    async with stdio_client(_server_params(mcp_graph)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("smp_navigate", {"query": "validate"})
    assert result.content, "expected tool result content"
    payload = json.loads(result.content[0].text)
    assert payload["entity"]["name"] == "validate"
    assert payload["entity"]["file_path"].endswith("app.py")


@pytest.mark.asyncio
async def test_mcp_impact_end_to_end(mcp_graph: Path) -> None:
    """An agent can run impact analysis through the MCP tool."""
    async with stdio_client(_server_params(mcp_graph)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("smp_impact", {"entity": "compute", "change_type": "modify"})
    payload = json.loads(result.content[0].text)
    assert "affected_functions" in payload
    # compute is called by handle (JS) — impact flows to callers.
    assert "handle" in payload["affected_functions"]
