"""Protocol layer — JSON-RPC 2.0 over FastAPI."""

from smp.protocol.router import handle_rpc
from smp.protocol.server import create_app

__all__ = [
    "create_app",
    "handle_rpc",
]
