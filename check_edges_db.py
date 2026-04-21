import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from smp.store.graph.neo4j_store import Neo4jGraphStore

async def main():
    store = Neo4jGraphStore()
    await store.connect()
    
    # Get all edges
    cypher = "MATCH (a)-[r]->(b) RETURN a.id, type(r), b.id LIMIT 20"
    results = await store._execute(cypher, {})
    
    print("=== All edges in database ===")
    for r in results:
        print(f"  {r['a.id']} --[{r['type(r)']}]--> {r['b.id']}")
    
    # Find compute_complex_metric
    node = await store.get_node("compute_complex_metric")
    if not node:
        # Try full ID
        candidates = await store.find_nodes(name="compute_complex_metric")
        print(f"\n=== Candidates for compute_complex_metric ===")
        for c in candidates:
            print(f"  {c.id}")
        if candidates:
            node = candidates[0]
    
    if node:
        print(f"\n=== Node found: {node.id} ===")
        
        # Get incoming edges
        incoming = await store.get_edges(node.id, direction="incoming")
        print(f"\n=== Incoming edges to {node.id} ===")
        for e in incoming:
            print(f"  {e.source_id} --[{e.type.value}]--> {e.target_id}")
        
        # Get outgoing edges
        outgoing = await store.get_edges(node.id, direction="outgoing")
        print(f"\n=== Outgoing edges from {node.id} ===")
        for e in outgoing:
            print(f"  {e.source_id} --[{e.type.value}]--> {e.target_id}")

if __name__ == "__main__":
    asyncio.run(main())
