from __future__ import annotations

import asyncio
from typing import Any
import msgspec

from smp.engine.query import DefaultQueryEngine
from smp.store.graph.neo4j_store import Neo4jGraphStore

async def run_tool(tool_name: str, *args: str) -> None:
    """Run a specific SMP tool and print the result to stdout.
    
    Args:
        tool_name: The name of the tool to call (locate, navigate, flow, impact, search)
        args: Arguments passed to the tool.
    """
    uri = "bolt://localhost:7687"
    user = "neo4j"
    password = "123456789$Do"
    
    store = Neo4jGraphStore(
        uri=uri, user=user, password=password
    )
    await store.connect()
    engine = DefaultQueryEngine(store)
    
    try:
        if tool_name == "locate":
            result = await engine.locate(args[0])
            print(msgspec.json.encode(result).decode())
        elif tool_name == "navigate":
            result = await engine.navigate(args[0])
            print(msgspec.json.encode(result).decode())
        elif tool_name == "flow":
            result = await engine.find_flow(args[0], args[1])
            print(msgspec.json.encode(result).decode())
        elif tool_name == "impact":
            result = await engine.assess_impact(args[0])
            print(msgspec.json.encode(result).decode())
        elif tool_name == "search":
            result = await engine.search(args[0])
            print(msgspec.json.encode(result).decode())
        else:
            print(f"Error: Unknown tool {tool_name}")
    finally:
        await store.close()

def main():
    import sys
    if len(sys.argv) < 3:
        print("Usage: smp-tool <tool_name> <args...>")
        sys.exit(1)
    
    tool_name = sys.argv[1]
    args = sys.argv[2:]
    
    asyncio.run(run_tool(tool_name, *args))

if __name__ == "__main__":
    main()
