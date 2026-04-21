"""
Diagnose why Rust functions aren't being extracted during SMP update.
"""
from __future__ import annotations
import asyncio
from smp.parser.rust_parser import RustParser
from smp.parser.registry import ParserRegistry
from smp.engine.graph_builder import DefaultGraphBuilder
from smp.store.graph.neo4j_store import Neo4jGraphStore

code = """
pub fn compute_complex_metric(data: f64) -> f64 {
    let scaled = data * 42.0;
    return apply_offset(scaled);
}

fn apply_offset(val: f64) -> f64 {
    return val + 1.5;
}
"""

async def diagnose():
    print("Step 1: Test RustParser directly...")
    parser = RustParser()
    result = parser.parse(code, "test.rs")
    print(f"  Parser returned: {len(result.nodes)} nodes, {len(result.edges)} edges")
    for node in result.nodes:
        print(f"    - {node.type}: {node.structural.name}")
    
    print("\nStep 2: Test via ParserRegistry...")
    registry = ParserRegistry()
    from smp.core.models import Language
    rust_parser = registry.get(Language.RUST)
    if rust_parser:
        result2 = rust_parser.parse(code, "test.rs")
        print(f"  Registry parser returned: {len(result2.nodes)} nodes, {len(result2.edges)} edges")
        for node in result2.nodes:
            print(f"    - {node.type}: {node.structural.name}")
    
    print("\nStep 3: Test via DefaultGraphBuilder...")
    graph = Neo4jGraphStore(uri="bolt://localhost:7688", user="neo4j", password="TestPassword123")
    await graph.connect()
    builder = DefaultGraphBuilder(graph)
    
    # Delete old test nodes
    all_nodes = await graph.find_nodes(file_path="test.rs")
    for node in all_nodes:
        print(f"  Deleting existing node: {node.structural.name}")
        await graph.delete_node(node.id)
    
    result3 = await builder.ingest("test.rs", code, "modified")
    print(f"  Builder returned: nodes={result3.get('nodes')}, edges={result3.get('edges')}")
    
    # Query the graph
    test_nodes = await graph.find_nodes(file_path="test.rs")
    print(f"  Graph contains: {len(test_nodes)} nodes")
    for node in test_nodes:
        print(f"    - {node.type}: {node.structural.name}")
    
    await graph.close()

if __name__ == "__main__":
    asyncio.run(diagnose())
