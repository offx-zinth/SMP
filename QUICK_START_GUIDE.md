# SMP Quick Start Guide

## What is SMP?

SMP (Structural Memory Protocol) is a **codebase intelligence system** that turns source code into a queryable knowledge graph. Instead of RAG (retrieval-augmented generation) treating code as flat text, SMP understands code **structure**:

- **Nodes**: Functions, classes, files, interfaces
- **Edges**: Calls, imports, inheritance, tests, references
- **Metadata**: Docstrings, comments, type hints, decorators, tags
- **Communities**: Architectural clusters and boundaries
- **Blast Radius**: Impact analysis for changes

Perfect for AI agents that need to safely understand and modify large codebases.

---

## Installation

### Prerequisites
- Python 3.11+ (required)
- Neo4j database running
- Optional: ChromaDB for vector search

### Setup
```bash
# Clone and enter directory
cd /home/bhagyarekhab/SMP

# Create virtual environment with Python 3.11
python3.11 -m venv .venv
source .venv/bin/activate

# Install in dev mode
pip install -e ".[dev]"

# Set up environment
cp .env.example .env
# Edit .env with your Neo4j credentials
```

### Docker Compose (Easiest)
```bash
docker-compose up -d
# Starts Neo4j, ChromaDB, and SMP server
```

---

## First Steps

### 1. Parse a Codebase
```bash
# Ingest a directory into the graph
python3.11 -m smp.cli ingest /path/to/your/code

# Or clear first (for testing)
python3.11 -m smp.cli ingest /path/to/your/code --clear
```

### 2. Start the Server
```bash
# JSON-RPC API on port 8000
python3.11 -m smp.cli serve

# Or MCP server (for Claude Desktop)
python3.11 -m smp.protocol.mcp
```

### 3. Query the Graph
Using Python:
```python
import asyncio
from smp.client import JsonRpcClient

client = JsonRpcClient("http://localhost:8000")

# Navigate to a function
result = await client.call("smp/navigate", {"query": "login"})
print(result)

# Find what calls this function
result = await client.call("smp/trace", {
    "start": "src/auth/login.py::Function::login::10",
    "relationship": "CALLS",
    "depth": 2,
    "direction": "incoming"
})
print(result)
```

Using cURL:
```bash
# Navigate
curl -X POST http://localhost:8000/rpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "smp/navigate", "params": {"query": "login"}}'

# Get impact of deleting a function
curl -X POST http://localhost:8000/rpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 2, "method": "smp/impact", "params": {"entity": "login", "change_type": "delete"}}'
```

---

## Key Operations

### Query Operations

**Find an entity:**
```python
await client.call("smp/navigate", {
    "query": "authenticate_user"
})
```

**Trace dependencies:**
```python
await client.call("smp/trace", {
    "start": "src/auth.py::Function::login::15",
    "relationship": "CALLS",
    "depth": 3
})
```

**Get surrounding context (for editing):**
```python
await client.call("smp/context", {
    "file_path": "src/auth.py",
    "scope": "edit",
    "depth": 2
})
```

**Find blast radius before deleting:**
```python
await client.call("smp/impact", {
    "entity": "src/auth.py::Function::old_function::42",
    "change_type": "delete"
})
```

### Memory Operations

**Ingest a new file:**
```python
with open("src/new_module.py") as f:
    await client.call("smp/update", {
        "file_path": "src/new_module.py",
        "content": f.read(),
        "language": "python"
    })
```

**Enrich with metadata:**
```python
await client.call("smp/enrich", {
    "node_id": "src/auth.py::Function::login::15"
})
```

**Add custom tags:**
```python
await client.call("smp/tag", {
    "scope": "src/auth.py",
    "tags": ["api", "deprecated"],
    "action": "add"
})
```

### Safety Operations

**Create an editing session:**
```python
session = await client.call("smp/session/open", {
    "agent_id": "my_agent",
    "workspace": "feature_branch"
})
session_id = session["session_id"]
```

**Simulate changes before applying:**
```python
await client.call("smp/dryrun", {
    "changes": [
        {
            "file_path": "src/auth.py",
            "content": "new code here",
            "language": "python"
        }
    ]
})
```

**Lock files to prevent race conditions:**
```python
await client.call("smp/lock", {
    "node_ids": [
        "src/auth.py::Function::login::15",
        "src/auth.py::Class::Auth::5"
    ],
    "session_id": session_id
})
```

**Create checkpoint for rollback:**
```python
checkpoint = await client.call("smp/checkpoint", {
    "session_id": session_id,
    "name": "before_major_refactor"
})
```

**Close session:**
```python
await client.call("smp/session/close", {
    "session_id": session_id,
    "commit": True
})
```

### Community Operations

**Detect communities (architectural clusters):**
```python
await client.call("smp/community/detect", {
    "resolutions": [0.5, 1.0, 2.0]
})
```

**List communities:**
```python
await client.call("smp/community/list", {
    "level": 1
})
```

**Get community details:**
```python
await client.call("smp/community/get", {
    "community_id": "module_auth",
    "include_bridges": True
})
```

---

## MCP Integration (Claude Desktop)

### Start SMP as MCP Server
```bash
python3.11 -m smp.protocol.mcp
```

### Add to Claude Desktop
Edit `~/.config/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "smp": {
      "command": "python3.11",
      "args": ["-m", "smp.protocol.mcp"],
      "cwd": "/home/bhagyarekhab/SMP",
      "env": {
        "SMP_NEO4J_URI": "bolt://localhost:7687",
        "SMP_NEO4J_USER": "neo4j",
        "SMP_NEO4J_PASSWORD": "your_password"
      }
    }
  }
}
```

Restart Claude. Now you can use tools like:
- `smp_navigate` - Find code entities
- `smp_trace` - Trace dependencies
- `smp_context` - Get editing context
- `smp_impact` - Assess change impact
- `smp_session_open` - Start safe editing session
- And 40+ more tools!

---

## Project Structure at a Glance

```
smp/
├── core/          Data models (GraphNode, GraphEdge, etc.)
├── engine/        Logic (query, graph building, enrichment, community)
├── parser/        AST extraction (Python, TypeScript)
├── protocol/      API layer (FastAPI, JSON-RPC, MCP)
│   └── handlers/  37+ handler implementations
├── sandbox/       Isolated execution
└── store/         Persistence (Neo4j, ChromaDB)

tests/            Comprehensive test suite
```

---

## Common Workflows

### Workflow 1: Safe Refactoring
```python
# 1. Understand the code
context = await client.call("smp/context", {"file_path": "src/auth.py"})

# 2. Check impact of changes
impact = await client.call("smp/impact", {"entity": "old_function"})

# 3. Start safe session
session = await client.call("smp/session/open", {})

# 4. Lock critical nodes
await client.call("smp/lock", {"node_ids": [...], "session_id": session["session_id"]})

# 5. Simulate changes
await client.call("smp/dryrun", {"changes": [...]})

# 6. Create checkpoint
await client.call("smp/checkpoint", {"session_id": session["session_id"]})

# 7. Update code
await client.call("smp/update", {"file_path": "src/auth.py", "content": "..."})

# 8. Close session
await client.call("smp/session/close", {"session_id": session["session_id"], "commit": True})
```

### Workflow 2: Understand Architecture
```python
# Detect communities
communities = await client.call("smp/community/detect", {})

# List all modules
modules = await client.call("smp/community/list", {})

# Get module boundaries and coupling
boundaries = await client.call("smp/community/boundaries", {})
```

### Workflow 3: Add Documentation
```python
# Find all undocumented functions
nodes = await client.call("smp/locate", {
    "query": "missing_docstring",
    "node_types": ["Function"]
})

# Enrich each node
for node in nodes:
    await client.call("smp/enrich", {"node_id": node["id"]})

# Tag them
await client.call("smp/tag", {
    "scope": "src/",
    "tags": ["documented"],
    "action": "add"
})
```

---

## Testing

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_query.py -v

# Run with coverage
pytest --cov=smp tests/

# Run specific test
pytest tests/test_query.py::TestQueryEngine::test_navigate
```

---

## Debugging

### Enable verbose logging
```bash
export SMP_LOG_LEVEL=DEBUG
python3.11 -m smp.cli serve
```

### Inspect the Neo4j graph
```bash
# Connect to Neo4j Browser: http://localhost:7474
# Query all nodes
MATCH (n) RETURN n LIMIT 100

# Query specific functions
MATCH (n:Function) WHERE n.name CONTAINS 'login' RETURN n
```

### Test a handler directly
```python
from smp.protocol.handlers.query import NavigateHandler
handler = NavigateHandler()
result = await handler.handle(
    {"query": "login"},
    {"engine": my_engine}
)
print(result)
```

---

## Next Steps

1. **Explore docs:**
   - `README.md` - Full feature overview
   - `ARCHITECTURE.md` - Deep dive into design
   - `API.md` - Detailed API reference
   - `MCP_SERVER.md` - MCP integration details
   - `PROJECT_STRUCTURE.md` - This project structure

2. **Run tests** to understand the API:
   - `tests/test_query.py` - Query operations
   - `tests/test_integration_protocol_handlers.py` - Handler examples

3. **Start with a small codebase:**
   - `test_codebase/` - Small test project already included
   - Ingest it: `python3.11 -m smp.cli ingest tests/test_codebase`

4. **Build an agent:**
   - Use the Python client: `smp.client.JsonRpcClient`
   - Or use MCP tools directly in Claude

---

## Troubleshooting

### Neo4j connection refused
```bash
# Check if Neo4j is running
docker-compose ps

# Start Neo4j
docker-compose up -d neo4j
```

### Port already in use
```bash
# Change default port
python3.11 -m smp.cli serve --port 8001
```

### Out of memory during ingestion
```bash
# Increase max file size or use smaller batches
python3.11 -m smp.cli ingest /path --max-file-size 500000
```

### Type errors with mypy
```bash
# Make sure you're using Python 3.11+
python3.11 --version

# Reinstall in dev mode
pip install -e ".[dev]"
```

---

## Support

- Check `AGENTS.md` for agent development guide
- Check `CONTRIBUTING.md` for code contribution guidelines
- Review test files for usage examples
- Check `USER_GUIDE.md` for detailed workflows

