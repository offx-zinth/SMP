"""Test script to run the CodingAgent on auth.py and capture logs."""

import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from smp.client import SMPClient
from smp.agent import CodingAgent
from smp.logging import configure_logging, get_logger

configure_logging(json=False, level="INFO")
log = get_logger(__name__)


async def main():
    smp_url = "http://localhost:8420"
    file_path = "smp/demo/core_db.py"
    instruction = "Hey agent, edit low_level_query in core_db.py to require a db_name: str argument. Update the callers everywhere"
    gemini_api_key = None  # Will use GEMINI_API_KEY from env

    print(f"\n{'='*60}")
    print(f"Running CodingAgent on: {file_path}")
    print(f"Instruction: {instruction}")
    print(f"{'='*60}\n")

    async with SMPClient(smp_url) as client:
        agent = CodingAgent(client, gemini_api_key=gemini_api_key)

        try:
            result = await agent.run(file_path=file_path, instruction=instruction)

            print(f"\n{'='*60}")
            print("AGENT RESULT")
            print(f"{'='*60}")
            print(f"File: {result.file_path}")
            print(f"Instruction: {result.instruction}")
            print(f"Nodes synced: {result.nodes_synced}")
            print(f"Edges synced: {result.edges_synced}")
            print(f"Summary: {result.summary}")
            print(f"\n--- Original Content ---\n{result.original_content[:500]}...")
            print(f"\n--- Edited Content ---\n{result.edited_content[:500]}...")
            print(f"\n--- Context Nodes ---")
            for n in result.context.get("nodes", [])[:10]:
                print(f"  {n['type']}: {n['name']} (L{n['start_line']}-{n['end_line']})")
            print(f"\n--- Impact ---")
            print(f"  Total affected: {result.impact.get('total_affected', 0)}")
            for a in result.impact.get("affected_nodes", [])[:5]:
                print(f"  - {a['type']}: {a['name']} in {a['file_path']}")

        except Exception as e:
            log.error("agent_failed", error=str(e), exc_info=True)
            print(f"\nERROR: {e}")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
