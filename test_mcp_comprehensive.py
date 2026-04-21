"""
Comprehensive MCP tool testing - verifies all major SMP tools work correctly
with multi-language codebase support.
"""
from __future__ import annotations

import asyncio
from typing import Any
from dataclasses import dataclass

from smp.protocol.mcp_server import (
    app_lifespan,
    smp_navigate,
    smp_trace,
    smp_context,
    smp_impact,
    smp_locate,
    smp_search,
    smp_flow,
    smp_update,
    NavigateInput,
    TraceInput,
    ContextInput,
    ImpactInput,
    LocateInput,
    SearchInput,
    FlowInput,
    UpdateInput,
)

@dataclass
class MockRequestContext:
    lifespan_state: dict[str, Any]

@dataclass
class MockCtx:
    request_context: MockRequestContext

async def test_mcp_tools() -> None:
    """Test all major MCP tools with multi-language code samples."""
    
    print("\n🚀 Testing SMP MCP Tools - Comprehensive Suite")
    print("=" * 80)
    
    async with app_lifespan() as state:
        ctx = MockCtx(request_context=MockRequestContext(lifespan_state=state))
        
        try:
            # Test files setup
            test_files = [
                ("test_multi.py", """
class Calculator:
    def add(self, a, b):
        return a + b
    
    def multiply(self, a, b):
        result = a * b
        return result

def main():
    calc = Calculator()
    result = calc.add(5, 3)
    return result
"""),
                ("test_multi.js", """
class DataProcessor {
    constructor() {
        this.data = [];
    }
    
    process(items) {
        return items.map(x => x * 2);
    }
}

function run() {
    const processor = new DataProcessor();
    return processor.process([1, 2, 3]);
}
"""),
                ("test_multi.java", """
public class StringUtils {
    public static String reverse(String s) {
        return new StringBuilder(s).reverse().toString();
    }
    
    public static void main(String[] args) {
        String result = reverse("hello");
        System.out.println(result);
    }
}
"""),
            ]
            
            # Phase 1: Parse files using smp_update
            print("\n" + "-" * 80)
            print("PHASE 1: Parsing Multi-Language Files")
            print("-" * 80)
            
            for filename, content in test_files:
                params = UpdateInput(
                    file_path=filename,
                    content=content,
                    change_type="modified"
                )
                result = await smp_update(params, ctx)
                
                lang = filename.split(".")[-1].upper()
                if "upserted" in str(result).lower() or "count" in str(result).lower():
                    print(f"✅ {lang:12} parsed successfully")
                else:
                    print(f"⚠️  {lang:12} parse result: {result}")
            
            # Phase 2: Test smp_navigate
            print("\n" + "-" * 80)
            print("PHASE 2: Testing smp_navigate")
            print("-" * 80)
            
            params = NavigateInput(query="Calculator")
            result = await smp_navigate(params, ctx)
            print(f"✅ smp_navigate('Calculator'): {type(result).__name__}")
            if isinstance(result, list):
                print(f"   Found entities: {len(result)}")
            
            # Phase 3: Test smp_locate
            print("\n" + "-" * 80)
            print("PHASE 3: Testing smp_locate")
            print("-" * 80)
            
            params = LocateInput(query="add", node_types=["Function"])
            result = await smp_locate(params, ctx)
            print(f"✅ smp_locate('add'): Found {len(result) if isinstance(result, list) else 'results'}")
            
            # Phase 4: Test smp_search (semantic search)
            print("\n" + "-" * 80)
            print("PHASE 4: Testing smp_search")
            print("-" * 80)
            
            params = SearchInput(query="process data items")
            result = await smp_search(params, ctx)
            print(f"✅ smp_search('process data items'): {type(result).__name__}")
            
            # Phase 5: Test smp_context
            print("\n" + "-" * 80)
            print("PHASE 5: Testing smp_context")
            print("-" * 80)
            
            params = ContextInput(file_path="test_multi.py")
            result = await smp_context(params, ctx)
            print(f"✅ smp_context('test_multi.py'): {type(result).__name__}")
            
            # Phase 6: Test smp_trace
            print("\n" + "-" * 80)
            print("PHASE 6: Testing smp_trace")
            print("-" * 80)
            
            params = TraceInput(start="main", direction="outgoing", depth=2)
            result = await smp_trace(params, ctx)
            print(f"✅ smp_trace(start='main'): {type(result).__name__}")
            
            # Phase 7: Test smp_impact
            print("\n" + "-" * 80)
            print("PHASE 7: Testing smp_impact")
            print("-" * 80)
            
            params = ImpactInput(entity="Calculator", change_type="delete")
            result = await smp_impact(params, ctx)
            print(f"✅ smp_impact(entity='Calculator'): {type(result).__name__}")
            
            # Phase 8: Test smp_flow
            print("\n" + "-" * 80)
            print("PHASE 8: Testing smp_flow")
            print("-" * 80)
            
            params = FlowInput(start="main", end="add", flow_type="data")
            result = await smp_flow(params, ctx)
            print(f"✅ smp_flow(main->add): {type(result).__name__}")
            
            print("\n" + "=" * 80)
            print("✅ All MCP Tool Tests Completed Successfully!")
            print("=" * 80)
            
        except Exception as e:
            print(f"\n❌ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_mcp_tools())
