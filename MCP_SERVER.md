# SMP as MCP Server

The Structural Memory Protocol (SMP) is now available as a **Model Context Protocol (MCP) Server**, enabling AI agents to query and manipulate code knowledge graphs through a standardized interface.

## Overview

**File:** `smp/protocol/mcp.py`

The MCP server wraps SMP's JSON-RPC 2.0 API as MCP tools and resources, making all SMP capabilities accessible to Claude and other MCP-compatible AI agents.

## Supported Tools (36 total)

### Graph Intelligence (8 tools)
Query and navigate the code knowledge graph:
- `smp_navigate` - Search for entities and their relationships
- `smp_trace` - Trace dependencies and references across the graph
- `smp_context` - Extract surrounding context for a file
- `smp_impact` - Assess the impact of changes
- `smp_locate` - Find specific code entities
- `smp_search` - Semantic search using vector embeddings
- `smp_flow` - Find paths or flows between entities
- `smp_why` - Explain why relationships exist

### Memory & Enrichment (10 tools)
Update the graph and enhance code understanding:
- `smp_update` - Update or ingest a file
- `smp_batch_update` - Apply multiple file updates
- `smp_reindex` - Reindex the graph
- `smp_enrich` - Enrich a node with semantic metadata
- `smp_enrich_batch` - Batch enrich multiple nodes
- `smp_enrich_stale` - Find stale enriched nodes
- `smp_enrich_status` - Check enrichment coverage
- `smp_annotate` - Manually annotate a node
- `smp_annotate_bulk` - Bulk annotation
- `smp_tag` - Add/remove/replace tags

### Safety & Integrity (10 tools)
Manage session safety and verify integrity:
- `smp_session_open` - Open a safety session
- `smp_session_close` - Close a session
- `smp_guard_check` - Check against safety guards
- `smp_dryrun` - Simulate a change
- `smp_checkpoint` - Create recovery checkpoint
- `smp_rollback` - Restore to checkpoint
- `smp_lock` - Lock files
- `smp_unlock` - Unlock files
- `smp_audit_get` - Retrieve audit logs
- `smp_verify_integrity` - Verify node integrity

### Execution & Sandbox (3 tools)
Execute code in isolated environments:
- `smp_sandbox_spawn` - Create sandbox
- `smp_sandbox_execute` - Execute commands
- `smp_sandbox_destroy` - Destroy sandbox

### Coordination & Observability (5 tools)
Manage handoffs and monitor execution:
- `smp_handoff_review` - Create code review
- `smp_handoff_approve` - Approve review
- `smp_handoff_reject` - Reject review
- `smp_handoff_pr` - Create pull request
- `smp_telemetry` - Query telemetry data

### System Resources (2 resources)
- `smp://stats` - System statistics
- `smp://health` - Health status

## Getting Started

### Prerequisites
- Python 3.11+
- Neo4j database running
- Chroma vector store configured
- Environment variables set:
  - `SMP_NEO4J_URI` (default: `bolt://localhost:7687`)
  - `SMP_NEO4J_USER` (default: `neo4j`)
  - `SMP_NEO4J_PASSWORD`
  - `SMP_SAFETY_ENABLED` (optional: `true`/`false`)

### Starting the Server

```bash
# Start as stdio server (for local use with Claude Desktop)
python3.11 -m smp.protocol.mcp

# Or as background process
python3.11 -m smp.cli run smp-mcp -- python3.11 -m smp.protocol.mcp
```

### Claude Desktop Integration

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "smp": {
      "command": "python3.11",
      "args": ["-m", "smp.protocol.mcp"],
      "cwd": "/path/to/SMP"
    }
  }
}
```

## Architecture

### Lifespan Management
The server uses `app_lifespan()` to:
1. Initialize Neo4j graph store
2. Connect Chroma vector store
3. Create embedding service
4. Set up query engines and builders
5. Optionally enable safety features
6. Provide state to all tools via FastMCP context

### Tool Pattern
Each MCP tool:
1. Accepts Pydantic-validated input
2. Retrieves server state from context
3. Routes to SMP's dispatcher via `_call_rpc()`
4. Returns structured results

### Error Handling
- Pydantic validation errors → `-32602` (Invalid params)
- Handler errors → `-32001` (Server error)
- Internal errors → `-32603` (Internal error)
- Method not found → `-32601` (Method not found)

## Example Usage

### With Claude Desktop
```
User: "Show me all functions in main.py that have complex dependencies"
Agent: [Calls smp_locate with query="functions" and file filter]

User: "What would break if I deleted this function?"
Agent: [Calls smp_impact to assess change effects]

User: "Create a code review for these changes"
Agent: [Calls smp_handoff_review]
```

### Programmatic (Python)
```python
from smp.protocol.mcp import mcp
import asyncio

async def query_graph():
    # Use the dispatcher to call tools
    from smp.protocol.dispatcher import get_dispatcher
    dispatcher = get_dispatcher()
    
    handler = dispatcher.get_handler("smp/navigate")
    result = await handler.handle(
        {"query": "find_function"},
        context={...}
    )
    return result

asyncio.run(query_graph())
```

## Configuration

### Environment Variables
```bash
# Neo4j
SMP_NEO4J_URI=bolt://localhost:7687
SMP_NEO4J_USER=neo4j
SMP_NEO4J_PASSWORD=your_password

# Safety Features
SMP_SAFETY_ENABLED=true

# Logging
RUST_LOG=info
```

### Safety Mode
When `SMP_SAFETY_ENABLED=true`, the following are initialized:
- SessionManager - Track agent sessions
- GuardEngine - Enforce safety checks
- CheckpointManager - Create recovery points
- AuditLogger - Log all changes
- SandboxExecutor - Isolated code execution

## Performance

- **Graph traversal**: O(depth) where depth is user-specified
- **Vector search**: O(log n) with ChromaDB indexing
- **Enrichment**: Batched for efficiency
- **Concurrent sessions**: Supported with locking

## Security

- Session-based isolation
- File locking for concurrent access
- Guard checks for destructive operations
- Audit logging of all changes
- Sandboxed execution environment

## Troubleshooting

### Server won't start
```bash
# Check Python version
python3.11 --version

# Check dependencies
pip list | grep mcp

# Verify Neo4j connection
telnet localhost 7687
```

### Tools not appearing in Claude
- Restart Claude Desktop
- Check `claude_desktop_config.json` syntax
- Verify server process is running

### Performance issues
- Check `SMP_NEO4J_URI` points to local instance
- Verify ChromaDB is running
- Monitor Neo4j memory usage

## Implementation Details

**File Structure:**
```
smp/
├── protocol/
│   ├── mcp.py          ← MCP Server (you are here)
│   ├── dispatcher.py   ← Route to handlers
│   ├── router.py       ← Legacy JSON-RPC router
│   ├── handlers/       ← Tool implementations
│   └── server.py       ← FastAPI endpoint
```

**Key Components:**
1. `app_lifespan()` - Initialize and manage server resources
2. `_call_rpc()` - Route MCP tools to SMP handlers
3. Pydantic models - Validate all tool inputs
4. MCP decorators - Register tools and resources
5. Annotations - Mark tools as read-only/destructive

## Future Enhancements

- [ ] Streaming for large result sets
- [ ] Caching frequently accessed paths
- [ ] Incremental graph updates
- [ ] Machine learning model integration
- [ ] Custom graph analyzers
- [ ] Remote Neo4j support with auth

## Contributing

When adding new tools:
1. Create Pydantic input model
2. Create MCP tool function
3. Add to appropriate tool category comment
4. Include docstring with examples
5. Test with `ruff check` and `mypy`
6. Update tool count in this document

## References

- MCP Specification: https://modelcontextprotocol.io
- FastMCP Documentation: https://github.com/modelcontextprotocol/python-sdk
- SMP Protocol: See PROTOCOL.md
