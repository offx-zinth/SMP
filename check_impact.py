import asyncio
import os
from smp.protocol.mcp_server import app_lifespan, smp_impact, ImpactInput
from smp.protocol.mcp_server import smp_update, UpdateInput

async def main():
    state = await app_lifespan().__aenter__()
    ctx = type('MockCtx', (), {'request_context': type('MockReq', (), {'lifespan_state': state})})()
    
    # Ingest test data
    files = {
        "/home/bhagyarekhab/SMP/mcp_eval_project/api.py": open("/home/bhagyarekhab/SMP/mcp_eval_project/api.py").read(),
        "/home/bhagyarekhab/SMP/mcp_eval_project/core.rs": open("/home/bhagyarekhab/SMP/mcp_eval_project/core.rs").read(),
        "/home/bhagyarekhab/SMP/mcp_eval_project/LegacyIntegration.java": open("/home/bhagyarekhab/SMP/mcp_eval_project/LegacyIntegration.java").read(),
    }
    for path, content in files.items():
        await smp_update(UpdateInput(file_path=path, content=content), ctx)

    # Check impact
    res = await smp_impact(ImpactInput(entity="compute_complex_metric", change_type="modify"), ctx)
    print(f"Impact Result: {res}")

if __name__ == "__main__":
    asyncio.run(main())
