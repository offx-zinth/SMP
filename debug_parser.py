import asyncio
import os
from dotenv import load_dotenv
load_dotenv()

from smp.protocol.mcp_server import app_lifespan
from smp.parser.registry import ParserRegistry
from smp.parser.base import detect_language
from smp.core.models import Language

async def main():
    state = await app_lifespan().__aenter__()
    
    # Read the core.rs file
    with open("/home/bhagyarekhab/SMP/mcp_eval_project/core.rs", "r") as f:
        content = f.read()
    
    print("\n=== CORE.RS CONTENT ===")
    print(content)
    print("======================")
    
    # Detect language
    lang = detect_language("/home/bhagyarekhab/SMP/mcp_eval_project/core.rs")
    print(f"Detected language: {lang}")
    
    # Get parser
    registry = ParserRegistry()
    parser = registry.get(lang)
    print(f"Parser: {parser}")
    
    if parser:
        # Parse the content
        doc = parser.parse(content, "/home/bhagyarekhab/SMP/mcp_eval_project/core.rs")
        print(f"\n=== PARSED DOCUMENT ===")
        print(f"Nodes: {len(doc.nodes)}")
        print(f"Edges: {len(doc.edges)}")
        
        print("\n--- Nodes ---")
        for node in doc.nodes:
            print(f"  {node.type.value}: {node.structural.name} ({node.id})")
            
        print("\n--- Edges ---")
        for edge in doc.edges:
            print(f"  {edge.source_id} --[{edge.type.value}]--> {edge.target_id}")
            
        if doc.errors:
            print("\n--- Errors ---")
            for error in doc.errors:
                print(f"  {error}")

if __name__ == "__main__":
    asyncio.run(main())
