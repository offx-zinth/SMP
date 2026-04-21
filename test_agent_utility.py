"""
Verify if SMP MCP tools are actually useful for AI agents by simulating a real-world workflow.
"""
from __future__ import annotations
import asyncio
from typing import Any
from dataclasses import dataclass

from smp.protocol.mcp_server import (
    app_lifespan, smp_update, smp_locate, smp_navigate, smp_trace, smp_impact,
    UpdateInput, LocateInput, NavigateInput, TraceInput, ImpactInput,
)

@dataclass
class MockRequestContext:
    lifespan_state: dict[str, Any]

@dataclass
class MockCtx:
    request_context: MockRequestContext

async def simulate_agent() -> None:
    async with app_lifespan() as state:
        ctx = MockCtx(request_context=MockRequestContext(lifespan_state=state))
        
        # Clear graph to avoid interference from diagnostic tests
        builder = state["builder"]
        await builder._store._execute("MATCH (n) DETACH DELETE n")
        print("\n🧹 Graph cleared for fresh simulation")
        
        print("\n🤖 AGENT: Starting investigation into Rust core impact...")
        print("=" * 80)


        # 1. Ingest the eval project
        # We use absolute paths to be safe
        files = {
            "/home/bhagyarekhab/SMP/mcp_eval_project/api.py": open("/home/bhagyarekhab/SMP/mcp_eval_project/api.py").read(),
            "/home/bhagyarekhab/SMP/mcp_eval_project/core.rs": open("/home/bhagyarekhab/SMP/mcp_eval_project/core.rs").read(),
            "/home/bhagyarekhab/SMP/mcp_eval_project/LegacyIntegration.java": open("/home/bhagyarekhab/SMP/mcp_eval_project/LegacyIntegration.java").read(),
        }
        for path, content in files.items():
            await smp_update(UpdateInput(file_path=path, content=content, change_type="modified"), ctx)
        
        print("\nStep 1: Navigating to the entry point function...")
        target = "compute_complex_metric"
        res_nav = await smp_navigate(NavigateInput(query=target), ctx)
        print(f"Navigate result: {res_nav}")
        
        target_node_id = None
        if isinstance(res_nav, dict) and "entity" in res_nav:
            target_node_id = res_nav["entity"]["id"]
        
        if not target_node_id:
            print("❌ FAILED: Could not navigate to entry point.")
            return


        print(f"\nStep 2: Analyzing impact (Who depends on this function?)...")
        res_impact = await smp_impact(ImpactInput(entity=target, change_type="modify"), ctx)
        print(f"Impact result: {res_impact}")

        print(f"\nStep 3: Tracing the call chain back to the API...")
        # Trace incoming calls
        res_trace = await smp_trace(TraceInput(start=target_node_id, direction="incoming", depth=5), ctx)
        print(f"Trace result: {res_trace}")

        print("\n" + "=" * 80)
        print("🤖 AGENT CONCLUSION:")
        
        # Check if we found the link to api.py
        found_link = False
        trace_nodes = res_trace.get("nodes", []) if isinstance(res_trace, dict) else res_trace
        if isinstance(trace_nodes, list):
            for node in trace_nodes:
                if "api.py" in node.get("file_path", ""):
                    found_link = True
                    break

        
        if found_link:
            print("✅ SUCCESS: I can see that changing 'compute_complex_metric' in core.rs affects 'handle_request' in api.py.")
        else:
            print("❌ FAILURE: I could not link the Rust function back to the Python API.")

if __name__ == "__main__":
    asyncio.run(simulate_agent())

