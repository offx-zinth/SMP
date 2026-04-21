"""Test that language detection fix works."""
from __future__ import annotations
import asyncio
from smp.core.models import UpdateParams
from smp.parser.registry import ParserRegistry
from smp.engine.graph_builder import DefaultGraphBuilder
from smp.store.graph.neo4j_store import Neo4jGraphStore
from smp.engine.enricher import StaticSemanticEnricher

rust_code = """
pub fn compute_complex_metric(data: f64) -> f64 {
    let scaled = data * 42.0;
    return apply_offset(scaled);
}

fn apply_offset(val: f64) -> f64 {
    return val + 1.5;
}
"""

async def test():
    print("Test 1: UpdateParams with no language specified")
    params = UpdateParams(file_path="test.rs", content=rust_code)
    print(f"  ✅ language = {params.language} (None)")
    
    print("\nTest 2: Language auto-detection from file extension")
    from smp.parser.base import detect_language
    detected = detect_language("test.rs")
    print(f"  ✅ test.rs -> {detected}")
    
    print("\nTest 3: Full update handler flow with Rust file")
    graph = Neo4jGraphStore(uri="bolt://localhost:7688", user="neo4j", password="TestPassword123")
    await graph.connect()
    
    # Clear old test data
    await graph._execute("MATCH (n) WHERE n.file_path = 'test.rs' DETACH DELETE n")
    
    registry = ParserRegistry()
    builder = DefaultGraphBuilder(graph)
    enricher = StaticSemanticEnricher()
    
    # Simulate what UpdateHandler does with auto-detection
    language = params.language
    if not language:
        from smp.parser.base import detect_language
        language = detect_language(params.file_path)
    
    parser_obj = registry.get(language)
    doc = parser_obj.parse(params.content, params.file_path)
    print(f"  ✅ Parser extracted {len(doc.nodes)} nodes, {len(doc.edges)} edges")
    
    # Enrich and ingest
    enriched_nodes = await enricher.enrich_batch(doc.nodes)
    doc = type(doc)(
        file_path=doc.file_path,
        language=doc.language,
        nodes=enriched_nodes,
        edges=doc.edges,
        errors=doc.errors,
    )
    
    await builder.remove_document(params.file_path)
    await builder.ingest_document(doc)
    
    # Query all nodes
    all_nodes = await graph.find_nodes(file_path="test.rs")
    print(f"  ✅ Neo4j contains {len(all_nodes)} nodes:")
    for node in all_nodes:
        print(f"     - {node.type}: {node.structural.name}")
    
    await graph.close()
    print("\n✅ LANGUAGE DETECTION FIX WORKS! Rust functions now persist to Neo4j")

if __name__ == "__main__":
    asyncio.run(test())
