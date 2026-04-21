#!/usr/bin/env python3.11
"""Direct test of SMP MCP server tools."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add SMP to path
sys.path.insert(0, str(Path(__file__).parent))

from smp.protocol.mcp_server import app_lifespan, mcp


async def test_smp_via_mcp():
    """Test SMP MCP tools directly."""
    
    print("🚀 Testing SMP Multi-Language Parsers via MCP")
    print("=" * 70)
    
    # Get the app lifespan context
    async with app_lifespan() as state:
        print("✅ MCP Server initialized")
        
        # Create a mock request context
        class MockRequestContext:
            lifespan_state = state
        
        class MockCtx:
            request_context = MockRequestContext()
        
        ctx = MockCtx()
        
        # Test 1: Parse Python
        print("\n" + "-" * 70)
        print("TEST 1: Parse Python File")
        print("-" * 70)
        
        python_code = """
def greet(name: str) -> str:
    '''Greet someone by name.'''
    return f"Hello, {name}!"

class Calculator:
    def add(self, a: int, b: int) -> int:
        '''Add two numbers.'''
        return a + b
"""
        
        try:
            from smp.core.models import UpdateParams
            params = UpdateParams(
                file_path="test.py",
                content=python_code,
                language="python"
            )
            # Get the handler directly
            from smp.protocol.dispatcher import get_dispatcher
            dispatcher = get_dispatcher()
            handler = dispatcher.get_handler("smp/update")
            
            result = await handler.handle(
                {"file_path": "test.py", "content": python_code, "language": "python"},
                state
            )
            print(f"✅ Python parsed successfully!")
            print(f"   Nodes: {result.get('nodes', 0)}")
            print(f"   Edges: {result.get('edges', 0)}")
        except Exception as e:
            print(f"❌ Error: {e}")
        
        # Test 2: Parse Java
        print("\n" + "-" * 70)
        print("TEST 2: Parse Java File")
        print("-" * 70)
        
        java_code = """
public class Calculator {
    public int add(int a, int b) {
        return a + b;
    }
    
    public int multiply(int x, int y) {
        return x * y;
    }
}
"""
        
        try:
            from smp.protocol.dispatcher import get_dispatcher
            dispatcher = get_dispatcher()
            handler = dispatcher.get_handler("smp/update")
            
            result = await handler.handle(
                {"file_path": "Calculator.java", "content": java_code, "language": "java"},
                state
            )
            print(f"✅ Java parsed successfully!")
            print(f"   Nodes: {result.get('nodes', 0)}")
            print(f"   Edges: {result.get('edges', 0)}")
        except Exception as e:
            print(f"❌ Error: {e}")
        
        # Test 3: Parse Rust
        print("\n" + "-" * 70)
        print("TEST 3: Parse Rust File")
        print("-" * 70)
        
        rust_code = """
pub struct Calculator;

impl Calculator {
    pub fn add(a: i32, b: i32) -> i32 {
        a + b
    }
    
    pub fn multiply(x: i32, y: i32) -> i32 {
        x * y
    }
}
"""
        
        try:
            from smp.protocol.dispatcher import get_dispatcher
            dispatcher = get_dispatcher()
            handler = dispatcher.get_handler("smp/update")
            
            result = await handler.handle(
                {"file_path": "calc.rs", "content": rust_code, "language": "rust"},
                state
            )
            print(f"✅ Rust parsed successfully!")
            print(f"   Nodes: {result.get('nodes', 0)}")
            print(f"   Edges: {result.get('edges', 0)}")
        except Exception as e:
            print(f"❌ Error: {e}")
        
        # Test 4: Parse Go
        print("\n" + "-" * 70)
        print("TEST 4: Parse Go File")
        print("-" * 70)
        
        go_code = """
package main

type Calculator struct{}

func (c *Calculator) Add(a, b int) int {
    return a + b
}

func Multiply(x, y int) int {
    return x * y
}
"""
        
        try:
            from smp.protocol.dispatcher import get_dispatcher
            dispatcher = get_dispatcher()
            handler = dispatcher.get_handler("smp/update")
            
            result = await handler.handle(
                {"file_path": "calc.go", "content": go_code, "language": "go"},
                state
            )
            print(f"✅ Go parsed successfully!")
            print(f"   Nodes: {result.get('nodes', 0)}")
            print(f"   Edges: {result.get('edges', 0)}")
        except Exception as e:
            print(f"❌ Error: {e}")
        
        # Test 5: Parse C++
        print("\n" + "-" * 70)
        print("TEST 5: Parse C++ File")
        print("-" * 70)
        
        cpp_code = """
#include <iostream>

class Calculator {
public:
    int add(int a, int b) {
        return a + b;
    }
    
    int multiply(int x, int y) {
        return x * y;
    }
};
"""
        
        try:
            from smp.protocol.dispatcher import get_dispatcher
            dispatcher = get_dispatcher()
            handler = dispatcher.get_handler("smp/update")
            
            result = await handler.handle(
                {"file_path": "calc.cpp", "content": cpp_code, "language": "cpp"},
                state
            )
            print(f"✅ C++ parsed successfully!")
            print(f"   Nodes: {result.get('nodes', 0)}")
            print(f"   Edges: {result.get('edges', 0)}")
        except Exception as e:
            print(f"❌ Error: {e}")
        
        print("\n" + "=" * 70)
        print("✅ All MCP Integration Tests Completed!")
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_smp_via_mcp())
