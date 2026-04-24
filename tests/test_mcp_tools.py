"""Integration tests for all 51 MCP tools."""

from __future__ import annotations

import pytest
from smp.mcp_server import mcp


class TestMCPToolDiscovery:
    """Test that all MCP tools are discoverable."""

    @pytest.mark.asyncio
    async def test_mcp_server_has_all_tools(self):
        """MCP server should expose all 51 tools."""
        tools = await mcp.list_tools()
        assert len(tools) == 51, f"Expected 51 tools, got {len(tools)}"

    @pytest.mark.asyncio
    async def test_navigate_tools_present(self):
        """All navigate/context tools should be present."""
        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        
        navigate_tools = {
            'smp_navigate', 'smp_trace', 'smp_context', 'smp_locate',
            'smp_search', 'smp_flow', 'smp_impact'
        }
        assert navigate_tools.issubset(tool_names)

    @pytest.mark.asyncio
    async def test_community_tools_present(self):
        """All community detection tools should be present."""
        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        
        community_tools = {
            'smp_community_detect', 'smp_community_list',
            'smp_community_get', 'smp_community_boundaries'
        }
        assert community_tools.issubset(tool_names)

    @pytest.mark.asyncio
    async def test_analysis_tools_present(self):
        """All code analysis tools should be present."""
        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        
        analysis_tools = {'smp_diff', 'smp_plan', 'smp_conflict'}
        assert analysis_tools.issubset(tool_names)

    @pytest.mark.asyncio
    async def test_integrity_tools_present(self):
        """All graph integrity tools should be present."""
        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        
        integrity_tools = {
            'smp_merkle_tree', 'smp_sync', 'smp_index_export', 'smp_index_import'
        }
        assert integrity_tools.issubset(tool_names)

    @pytest.mark.asyncio
    async def test_telemetry_tools_present(self):
        """All telemetry tools should be present."""
        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        
        telemetry_tools = {
            'smp_telemetry_hot', 'smp_telemetry_node',
            'smp_telemetry_record'
        }
        assert telemetry_tools.issubset(tool_names)

    @pytest.mark.asyncio
    async def test_session_recovery_present(self):
        """Session recovery tool should be present."""
        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        assert 'smp_session_recover' in tool_names

    @pytest.mark.asyncio
    async def test_safety_tools_present(self):
        """All safety and integrity tools should be present."""
        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        
        safety_tools = {
            'smp_session_open', 'smp_session_close', 'smp_session_recover',
            'smp_guard_check', 'smp_dryrun', 'smp_checkpoint',
            'smp_rollback', 'smp_verify_integrity', 'smp_lock', 'smp_unlock'
        }
        assert safety_tools.issubset(tool_names)

    @pytest.mark.asyncio
    async def test_sandbox_tools_present(self):
        """All sandbox execution tools should be present."""
        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        
        sandbox_tools = {
            'smp_sandbox_spawn', 'smp_sandbox_execute', 'smp_sandbox_destroy'
        }
        assert sandbox_tools.issubset(tool_names)

    @pytest.mark.asyncio
    async def test_handoff_tools_present(self):
        """All handoff/review tools should be present."""
        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        
        handoff_tools = {
            'smp_handoff_review', 'smp_handoff_approve',
            'smp_handoff_reject', 'smp_handoff_pr'
        }
        assert handoff_tools.issubset(tool_names)

    @pytest.mark.asyncio
    async def test_all_tools_have_descriptions(self):
        """All tools should have meaningful descriptions."""
        tools = await mcp.list_tools()
        
        for tool in tools:
            assert tool.description, f"Tool {tool.name} has no description"
            assert len(tool.description) > 10, (
                f"Tool {tool.name} has very short description: {tool.description}"
            )

    @pytest.mark.asyncio
    async def test_all_tools_have_input_schema(self):
        """All tools should have input schema."""
        tools = await mcp.list_tools()
        
        for tool in tools:
            assert tool.inputSchema, f"Tool {tool.name} has no inputSchema"


class TestMCPToolCategories:
    """Test tools are properly categorized."""

    @pytest.mark.asyncio
    async def test_tool_categories_count(self):
        """Verify tool distribution across categories."""
        tools = await mcp.list_tools()
        
        categories = {}
        for tool in tools:
            # Extract category from tool name (e.g., smp_community_detect -> community)
            parts = tool.name.replace('smp_', '').split('_')
            category = parts[0].upper()
            
            if category not in categories:
                categories[category] = 0
            categories[category] += 1
        
        # Verify major categories exist with expected counts
        assert 'NAVIGATE' in categories
        assert 'COMMUNITY' in categories
        assert categories['COMMUNITY'] == 4
        assert 'TELEMETRY' in categories


class TestMCPToolBackwardCompatibility:
    """Test backward compatibility with existing tools."""

    @pytest.mark.asyncio
    async def test_old_tools_still_available(self):
        """Original 5 basic tools should still be available."""
        tools = await mcp.list_tools()
        tool_names = {t.name for t in tools}
        
        old_tools = {
            'smp_locate', 'smp_navigate', 'smp_flow',
            'smp_impact', 'smp_search'
        }
        assert old_tools.issubset(tool_names)

    @pytest.mark.asyncio
    async def test_flow_tool_has_correct_schema(self):
        """smp_flow should have the correct input schema."""
        tools = await mcp.list_tools()
        flow_tool = next((t for t in tools if t.name == 'smp_flow'), None)
        
        assert flow_tool is not None
        # Schema has params with $ref to FlowInput definition
        schema = flow_tool.inputSchema
        assert 'properties' in schema
        assert 'params' in schema['properties']
        # FlowInput should have start and end in $defs
        assert '$defs' in schema
        assert 'FlowInput' in schema['$defs']
        assert 'start' in schema['$defs']['FlowInput']['properties']
        assert 'end' in schema['$defs']['FlowInput']['properties']
