import asyncio
import os
from dotenv import load_dotenv
load_dotenv()

from smp.protocol.mcp_server import app_lifespan, smp_impact, ImpactInput
from smp.protocol.mcp_server import smp_update, UpdateInput
from smp.store.graph.neo4j_store import Neo4jGraphStore
from smp.engine.query import DefaultQueryEngine
from smp.engine.enricher import StaticSemanticEnricher

async def main():
    state = await app_lifespan().__aenter__()
    ctx = type('MockCtx', (), {'request_context': type('MockReq', (), {'lifespan_state': state})})()
    
    # Get stores from state
    graph = state["graph"]
    enricher = state["enricher"] 
    engine = DefaultQueryEngine(graph, enricher)
    
    # Ingest test data
    files = {
        "/home/bhagyarekhab/SMP/mcp_eval_project/api.py": open("/home/bhagyarekhab/SMP/mcp_eval_project/api.py").read(),
        "/home/bhagyarekhab/SMP/mcp_eval_project/core.rs": open("/home/bhagyarekhab/SMP/mcp_eval_project/core.rs").read(),
        "/home/bhagyarekhab/SMP/mcp_eval_project/LegacyIntegration.java": open("/home/bhagyarekhab/SMP/mcp_eval_project/LegacyIntegration.java").read(),
    }
    for path, content in files.items():
        await smp_update(UpdateInput(file_path=path, content=content), ctx)

    print("=== Debugging Impact Analysis ===")
    
    # First check if we can find the entity
    nav = await graph.get_node("compute_complex_metric")
    print(f"Direct node lookup: {nav}")
    
    if not nav:
        # Try find by name
        candidates = await graph.find_nodes(name="compute_complex_metric")
        print(f"Find by name candidates: {len(candidates)}")
        if candidates:
            nav = candidates[0]
            print(f"Using first candidate: {nav.id}")
    
    # Now check impact manually
    if nav:
        print(f"\nAnalyzing impact for: {nav.id}")
        
        # Check what edges point TO this node (incoming CALLS)
        incoming = await graph.get_edges(nav.id, direction="incoming")
        print(f"Incoming edges: {len(incoming)}")
        for e in incoming:
            print(f"  {e.source_id} --[{e.type.value}]--> {e.target_id}")
            
        # Check outgoing edges too
        outgoing = await graph.get_edges(nav.id, direction="outgoing")
        print(f"Outgoing edges: {len(outgoing)}")
        for e in outgoing:
            print(f"  {e.source_id} --[{e.type.value}]--> {e.target_id}")
        
        # Try the actual impact assessment manually
        dependents = await graph.traverse(nav.id, [graph.store.interfaces.EdgeType.CALLS, graph.store.interfaces.EdgeType.CALLS_RUNTIME, graph.store.interfaces.EdgeType.DEPENDS_ON], depth=10, max_nodes=200, direction="incoming")
        print(f"\nManual traverse found {len(dependents)} dependents")
        for d in dependents[:5]:  # Show first 5
            print(f"  {d.id} ({d.file_path})")
            
        # Check if we're getting the right edge types
        edge_types_to_check = [graph.store.interfaces.EdgeType.CALLS, graph.store.interfaces.EdgeType.CALLS_RUNTIME, graph.store.interfaces.EdgeType.DEPENDS_ON]
        print(f"\nChecking for edge types: {[et.value for et in edge_types_to_check]}")
        
        # Try to get edges with these types specifically
        for edge_type in edge_types_to_check:
            edges = await graph.get_edges(nav.id, edge_type=edge_type, direction="incoming")
            print(f"  {edge_type.value}: {len(edges)} incoming edges")
            
    # Now call the actual smp_impact
    print("\n=== Calling smp_impact ===")
    try:
        res = await smp_impact(ImpactInput(entity="compute_complex_metric", change_type="modify"), ctx)
        print(f"Impact Result: {res}")
    except Exception as e:
        print(f"Error in smp_impact: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
