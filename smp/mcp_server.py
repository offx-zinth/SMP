"""MCP server entry point with all 51 SMP protocol tools.

This module re-exports the full FastMCP server from smp.protocol.mcp_server
to ensure agents can discover all available tools.
"""

from __future__ import annotations

# Import the complete MCP server with all 51 tools
from smp.protocol.mcp_server import mcp

__all__ = ["mcp"]

if __name__ == "__main__":
    mcp.run()
