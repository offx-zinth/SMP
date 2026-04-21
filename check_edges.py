import asyncio
from smp.store.graph.neo4j_store import Neo4jGraphStore

async def check():
    graph = Neo4jGraphStore(uri="bolt://localhost:7688", user="neo4j", password="TestPassword123")
    await graph.connect()
    
    # Check CALLS edges
    result = await graph._execute("MATCH (a)-[e:CALLS]->(b) RETURN a.name, b.name, type(e)")
    print("CALLS edges:")
    for rec in result:
        caller = rec[0] if rec[0] else "None"
        callee = rec[1] if rec[1] else "None"
        print(f"  {caller} -> {callee}")
    
    # Check CONTAINS edges
    result2 = await graph._execute("MATCH (a)-[e:CONTAINS]->(b) RETURN a.name, b.name LIMIT 5")
    print("\nCONTAINS edges:")
    for rec in result2:
        parent = rec[0] if rec[0] else "None"
        child = rec[1] if rec[1] else "None"
        print(f"  {parent} -> {child}")
    
    # Check reverse edges (called_by)
    result3 = await graph._execute("MATCH (a)<-[e:CALLS]-(b) RETURN a.name, b.name LIMIT 5")
    print("\nReverse CALLS (called_by):")
    for rec in result3:
        callee = rec[0] if rec[0] else "None"
        caller = rec[1] if rec[1] else "None"
        print(f"  {callee} <- {caller}")

    await graph.close()

asyncio.run(check())
