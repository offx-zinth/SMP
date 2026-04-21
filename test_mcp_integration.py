#!/usr/bin/env python3.11
"""Test script to interact with SMP MCP server via stdio."""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager

import msgspec
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import StdioTransport


async def test_smp_mcp():
    """Test SMP MCP server with multi-language parsing."""
    
    # Start the MCP server as a subprocess
    server_params = StdioServerParameters(
        command="python3.11",
        args=["smp/protocol/mcp_server.py"],
        env={"PYTHONPATH": "/home/bhagyarekhab/SMP"}
    )
    
    print("🔌 Connecting to SMP MCP Server...")
    
    try:
        async with ClientSession(StdioTransport(server_params)) as session:
            # Get available tools
            tools = await session.list_tools()
            print(f"\n✅ Connected! Available tools: {len(tools.tools)}")
            
            # List first 10 tools
            print("\nAvailable MCP Tools:")
            print("-" * 50)
            for tool in tools.tools[:15]:
                print(f"  • {tool.name:30} - {tool.description[:40]}")
            if len(tools.tools) > 15:
                print(f"  ... and {len(tools.tools) - 15} more tools")
            
            # Test 1: Update and parse a Python file
            print("\n" + "=" * 70)
            print("TEST 1: Parse Python File via SMP Update")
            print("=" * 70)
            
            python_code = '''
def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"

class Calculator:
    def add(self, a: int, b: int) -> int:
        """Add two numbers."""
        return a + b
'''
            
            result = await session.call_tool(
                "smp_update",
                {
                    "file_path": "test_python.py",
                    "content": python_code,
                    "language": "python"
                }
            )
            print(f"📝 Python parsing result:")
            print(f"   Nodes extracted: {result.content[0].text.get('nodes', 'N/A')}")
            print(f"   Edges created: {result.content[0].text.get('edges', 'N/A')}")
            
            # Test 2: Update and parse a Java file
            print("\n" + "=" * 70)
            print("TEST 2: Parse Java File via SMP Update")
            print("=" * 70)
            
            java_code = '''
public class Calculator {
    public int add(int a, int b) {
        return a + b;
    }
    
    public int multiply(int x, int y) {
        return x * y;
    }
}
'''
            
            result = await session.call_tool(
                "smp_update",
                {
                    "file_path": "Calculator.java",
                    "content": java_code,
                    "language": "java"
                }
            )
            print(f"📝 Java parsing result:")
            print(f"   Nodes extracted: {result.content[0].text.get('nodes', 'N/A')}")
            print(f"   Edges created: {result.content[0].text.get('edges', 'N/A')}")
            
            # Test 3: Update and parse a Rust file
            print("\n" + "=" * 70)
            print("TEST 3: Parse Rust File via SMP Update")
            print("=" * 70)
            
            rust_code = '''
pub struct Calculator;

impl Calculator {
    pub fn add(a: i32, b: i32) -> i32 {
        a + b
    }
    
    pub fn multiply(x: i32, y: i32) -> i32 {
        x * y
    }
}
'''
            
            result = await session.call_tool(
                "smp_update",
                {
                    "file_path": "calc.rs",
                    "content": rust_code,
                    "language": "rust"
                }
            )
            print(f"📝 Rust parsing result:")
            print(f"   Nodes extracted: {result.content[0].text.get('nodes', 'N/A')}")
            print(f"   Edges created: {result.content[0].text.get('edges', 'N/A')}")
            
            # Test 4: Navigate the graph
            print("\n" + "=" * 70)
            print("TEST 4: Navigate Graph via SMP Navigate")
            print("=" * 70)
            
            result = await session.call_tool(
                "smp_navigate",
                {"query": "test_python.py::Function::greet::1"}
            )
            if "error" in str(result.content[0].text):
                print(f"⚠️  Navigation note: {str(result.content[0].text)[:100]}")
            else:
                print(f"✅ Found entity in graph:")
                print(f"   {result.content[0].text}")
            
            # Test 5: Test search functionality
            print("\n" + "=" * 70)
            print("TEST 5: Search Graph via SMP Search")
            print("=" * 70)
            
            result = await session.call_tool(
                "smp_search",
                {
                    "query": "add two numbers",
                    "top_k": 5
                }
            )
            print(f"🔍 Search results:")
            print(f"   {result.content[0].text}")
            
            # Test 6: List available resources
            print("\n" + "=" * 70)
            print("TEST 6: Available MCP Resources")
            print("=" * 70)
            
            resources = await session.list_resources()
            print(f"📦 Available resources: {len(resources.resources)}")
            for resource in resources.resources:
                print(f"   • {resource.uri}")
            
            print("\n" + "=" * 70)
            print("✅ All MCP Tests Completed Successfully!")
            print("=" * 70)
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    success = asyncio.run(test_smp_mcp())
    sys.exit(0 if success else 1)
