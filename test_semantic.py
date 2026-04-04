"""
SMP Semantic Search Test
Testing if the LLM Vector DB understands the 'soul' of the code.
"""

import asyncio
from smp.client import SMPClient
from smp.logging import configure_logging

configure_logging(json=False, level="INFO")

async def main():
    smp_url = "http://localhost:8420"

    queries = [
        "Where is the code that scrubs private information and hides secrets?",
        "Which function talks directly to the physical hardware pins?",
        "Where do we calculate money and transactions?",
    ]

    async with SMPClient(smp_url) as client:
        for q in queries:
            print(f"\n{'='*60}")
            print(f"🔍 SEARCHING INTENT: '{q}'")
            print(f"{'='*60}")

            results = await client.locate(description=q, top_k=2)

            for i, res in enumerate(results, 1):
                node = res.get("node", {})
                score = res.get("score", 0.0)
                purpose = res.get("purpose", "No purpose found")

                print(f"\n[{i}] MATCH SCORE: {score:.4f}")
                print(f"    Name:    {node.get('name')}")
                print(f"    File:    {node.get('file_path')}")
                print(f"    Purpose: {purpose}")

if __name__ == "__main__":
    asyncio.run(main())
