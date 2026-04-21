"""Test specific scenarios to debug failures."""
from __future__ import annotations
import asyncio
from typing import Any
from dataclasses import dataclass
from smp.protocol.mcp_server import (
    app_lifespan, smp_update, smp_navigate, smp_search, smp_trace, smp_impact, smp_batch_update,
    UpdateInput, NavigateInput, SearchInput, TraceInput, ImpactInput, BatchUpdateInput,
)

@dataclass
class MockRequestContext:
    lifespan_state: dict[str, Any]

@dataclass
class MockCtx:
    request_context: MockRequestContext

async def test_scenario_2():
    """Debug Scenario 2: Impact Analysis"""
    state = await app_lifespan().__aenter__()
    ctx = MockCtx(request_context=MockRequestContext(lifespan_state=state))
    
    # Ingest test data
    files = {
        "/home/bhagyarekhab/SMP/mcp_eval_project/api.py": open("/home/bhagyarekhab/SMP/mcp_eval_project/api.py").read(),
        "/home/bhagyarekhab/SMP/mcp_eval_project/core.rs": open("/home/bhagyarekhab/SMP/mcp_eval_project/core.rs").read(),
        "/home/bhagyarekhab/SMP/mcp_eval_project/LegacyIntegration.java": open("/home/bhagyarekhab/SMP/mcp_eval_project/LegacyIntegration.java").read(),
    }
    changes = []
    for path, content in files.items():
        changes.append({"file_path": path, "content": content, "change_type": "modified"})
    
    await smp_batch_update(BatchUpdateInput(changes=changes), ctx)
    
    print("=== Scenario 2: Impact Analysis ===")
    
    # Step 1: Navigate
    try:
        nav = await smp_navigate(NavigateInput(query="compute_complex_metric"), ctx)
        print("Navigate result:", nav)
    except Exception as e:
        print(f"Navigate FAILED: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 2: Impact
    try:
        impact = await smp_impact(ImpactInput(entity="compute_complex_metric", change_type="modify"), ctx)
        print("Impact result:", impact)
    except Exception as e:
        print(f"Impact FAILED: {e}")
        import traceback
        traceback.print_exc()

async def test_scenario_13():
    """Debug Scenario 13: Dead Code Detection"""
    state = await app_lifespan().__aenter__()
    ctx = MockCtx(request_context=MockRequestContext(lifespan_state=state))
    
    print("\n=== Scenario 13: Dead Code Detection ===")
    
    # Step 1: Search for functions in Java
    try:
        search = await smp_search(SearchInput(query="java"), ctx)
        print("Search result:", search)
    except Exception as e:
        print(f"Search FAILED: {e}")
        import traceback
        traceback.print_exc()

print("Testing Scenarios 2 and 13...")
asyncio.run(test_scenario_2())
asyncio.run(test_scenario_13())
