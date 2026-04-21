import asyncio
from smp.store.graph.neo4j_store import Neo4jGraphStore

async def check():
    graph = Neo4jGraphStore(uri="bolt://localhost:7688", user="neo4j", password="TestPassword123")
    await graph.connect()
    
    # Check all relationship types
    result = await graph._execute("MATCH ()-[e]->() RETURN DISTINCT type(e) as rel_type")
    print("All relationship types in graph:")
    for rec in result:
        print(f"  {rec['rel_type'] if hasattr(rec, '__getitem__') else rec[0]}")
    
    # Check all edges
    result2 = await graph._execute("MATCH (a)-[e]->(b) RETURN a.structural, b.structural, type(e) LIMIT 10")
    print("\nSample edges:")
    for rec in result2:
        a_struct = rec[0] if hasattr(rec, '__getitem__') else rec['a.structural']
        b_struct = rec[1] if hasattr(rec, '__getitem__') else rec['b.structural']
        edge_type = rec[2] if hasattr(rec, '__getitem__') else rec['type(e)']
        a_name = a_struct.get('name', '?') if a_struct else '?'
        b_name = b_struct.get('name', '?') if b_struct else '?'
        print(f"  {a_name} -[{edge_type}]-> {b_name}")
    
    await graph.close()

asyncio.run(check())
