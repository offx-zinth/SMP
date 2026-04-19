import asyncio
import os

from smp.client import SMPClient
from smp.logging import get_logger

log = get_logger("verification")

async def main():
    async with SMPClient("http://localhost:8420") as client:
        # 1. Ingest Test Codebase
        log.info("Step 1: Ingesting test codebase")
        test_dir = "tests/test_codebase"
        files = ["math_utils.py", "calculator.py"]
        for f in files:
            path = os.path.join(test_dir, f)
            with open(path) as file:
                content = file.read()
            await client.update(path, content=content)
        
        stats = await client.stats()
        log.info("Graph stats after ingestion", stats=stats)

        # 2. Test Locate (Graph RAG)
        log.info("Step 2: Testing locate")
        results = await client.locate("adds two integers")
        log.info("Locate results", results=results)
        assert len(results) > 0, "Should have found the 'add' function"
        assert "add" in results[0]["name"], "First result should be 'add'"

        # 3. Test Navigate
        log.info("Step 3: Testing navigate")
        # Find the ID for compute_sum first
        res = await client.locate("compute sum")
        sum_id = res[0]["node_id"]
        nav = await client.navigate(sum_id)
        log.info("Navigate results", nav=nav)
        # Check if it mentions 'add'
        found_add = any("add" in str(v) for v in nav.values())
        assert found_add, "Navigate for compute_sum should reveal connection to add"

        # 4. Test Trace
        log.info("Step 4: Testing trace")
        # Trace who calls 'add'
        add_res = await client.locate("adds two integers")
        add_id = add_res[0]["node_id"]
        trace = await client.trace(add_id, direction="incoming")
        log.info("Trace results", trace=trace)
        assert len(trace) > 0, "Should find that compute_sum calls add"

        # 5. Test Community Detection
        log.info("Step 5: Testing community detection")
        comm_res = await client._rpc("smp/community/detect", {"levels": [{"level": 0, "resolution": 0.5}]})
        log.info("Community detect result", res=comm_res)
        assert "coarse_communities" in comm_res, "Should have detected communities"

        # 6. Test Merkle Sync
        log.info("Step 6: Testing Merkle Sync")
        root_hash = await client._rpc("smp/merkle/tree", {})
        log.info("Merkle root hash", hash=root_hash)
        assert root_hash is not None, "Should have a root hash"

        # 7. Test Safety Protocol
        log.info("Step 7: Testing Safety")
        session = await client._rpc("smp/session/open", {"agent_id": "test_agent", "task": "verify"})
        sid = session["session_id"]
        log.info("Session opened", sid=sid)
        
        lock_res = await client._rpc("smp/lock", {"file_path": "tests/test_codebase/math_utils.py", "session_id": sid})
        log.info("Lock acquired", res=lock_res)
        
        await client._rpc("smp/session/close", {"session_id": sid})
        log.info("Session closed")

        # 8. Test Sandbox
        log.info("Step 8: Testing Sandbox")
        sandbox = await client._rpc("smp/sandbox/spawn", {"name": "test_sb"})
        sb_id = sandbox["sandbox_id"]
        log.info("Sandbox spawned", sb_id=sb_id)
        
        exec_res = await client._rpc("smp/sandbox/execute", {"sandbox_id": sb_id, "command": ["ls", "-la"]})
        log.info("Sandbox execution", res=exec_res)
        assert exec_res["exit_code"] == 0, "Sandbox command should succeed"
        
        await client._rpc("smp/sandbox/destroy", {"sandbox_id": sb_id})
        log.info("Sandbox destroyed")

        log.info("ALL PRACTICAL TESTS PASSED")

if __name__ == "__main__":
    asyncio.run(main())
