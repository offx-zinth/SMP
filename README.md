# Structural Memory Protocol (SMP)

**High-Fidelity Codebase Intelligence for AI Agents**

Structural Memory Protocol (SMP) is a graph-based memory system that provides AI agents with a deep, structured understanding of complex codebases. Unlike RAG which treats code as flat text, SMP models code as a multi-dimensional graph of entities, relationships, and semantic meanings.

Built with **Python 3.11**, **FastAPI**, and **Neo4j**, SMP enables agents to perform precise code navigation, impact analysis, and safe refactoring — using static analysis (no LLM required).

---

## Quickstart (Docker Compose)

The fastest way to get SMP running:

```bash
# Clone the repository
git clone https://github.com/your-org/smp.git
cd smp

# Copy and configure environment
cp .env.example .env
# Edit .env with your Neo4j password

# Start all services
docker compose up -d

# Verify health
curl http://localhost:8420/health
# Returns: {"status":"ok"}
```

---

## Quickstart (Manual)

### 1. Requirements
- **Python 3.11+**
- **Neo4j 5.x** (Local or AuraDB)

### 2. Environment
```bash
# Copy the example and configure
cp .env.example .env

# Edit .env with your credentials:
#   SMP_NEO4J_PASSWORD=your_neo4j_password
```

### 3. Install & Run
```bash
# Clone and enter the repo
git clone https://github.com/offx-zinth/smp.git
cd smp

# Create venv with Python 3.11
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Start the server
smp serve
```

---

## Architecture: Manual Efficient Method (SMP V2)

SMP V2 is designed for production-grade efficiency. It relies on **static AST extraction** and **Neo4j full-text indexing** — no LLM or vector embeddings required.

- **Parser**: Tree-sitter extracts functions, classes, imports, and docstrings directly from AST.
- **Enricher**: Extracts docstrings, decorators, and type annotations statically.
- **Linker**: Namespaced cross-file resolution for CALLS edges.
- **Query Engine**: Neo4j full-text index (BM25) for keyword search.
- **Safety Protocol**: Session management, dry-runs, and isolated sandbox execution.

---

## Demo: JSON-RPC Query

Ingest a codebase and query it:

```bash
# Ingest a project
smp ingest /path/to/your/project

# Query via JSON-RPC
curl -X POST http://localhost:8420/rpc \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "smp/context",
    "params": {
      "file_path": "smp/core/models.py",
      "scope": "edit",
      "depth": 2
    },
    "id": 1
  }'
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "self": {
      "id": "smp/core/models.py::GraphNode",
      "type": "Class",
      "name": "GraphNode",
      "signature": "class GraphNode",
      "start_line": 130,
      "end_line": 220
    },
    "neighbors": [
      {
        "id": "smp/core/models.py::StructuralProperties",
        "type": "Class",
        "relationship": "CONTAINS"
      },
      {
        "id": "smp/core/models.py::SemanticProperties",
        "type": "Class", 
        "relationship": "CONTAINS"
      }
    ],
    "context": {
      "file": "smp/core/models.py",
      "imports": ["msgspec", "typing"],
      "defines": ["GraphNode", "GraphEdge", "NodeType", "EdgeType"]
    }
  },
  "id": 1
}
```

---

## Key Capabilities

* **Graph-Augmented Retrieval:** Navigate via `CALLS`, `INHERITS`, `IMPORTS` relationships
* **Semantic Search:** Neo4j full-text index (BM25) for keyword search across docstrings/tags
* **Static Enrichment:** Docstrings, decorators, and type annotations extracted from AST
* **Impact Assessment:** Determine the "blast radius" before changes
* **Safety & Sandboxing:** Session management, dry-runs, isolated execution
* **Multi-Language:** Python and TypeScript/JavaScript via Tree-sitter

---

## Architecture

```
smp/
├── smp/
│   ├── core/            # Models, logging
│   ├── engine/         # Query, enricher, linker, safety
│   ├── protocol/      # JSON-RPC 2.0 API
│   │   └── handlers/  # Modular method handlers
│   ├── store/         # Neo4j (graph + full-text)
│   ├── parser/        # Tree-sitter parsing
│   ├── sandbox/        # Isolated execution
│   ├── cli.py         # CLI
│   └── client.py      # Python SDK
├── tests/             # Test suite
└── .github/workflows/# CI/CD
```

---

## Usage

### Ingest a Project
```bash
smp ingest /path/to/project --clear
```

### Run Server
```bash
smp serve --port 8420 --safety
```

### Python SDK
```python
import asyncio
from smp.client import SMPClient

async def main():
    async with SMPClient("http://localhost:8420") as client:
        # Semantic search
        results = await client.locate("authentication logic")
        
        # Trace call graph
        graph = await client.trace("src/auth.py::login", depth=5)
        
        # Impact assessment
        impact = await client.assess_impact("src/models/user.py::User")
        print(f"Affects {impact['total_affected_nodes']} nodes")

asyncio.run(main())
```

---

## Development

```bash
# Format
ruff format .

# Lint
ruff check .

# Type check
mypy smp/

# Test
pytest
```

---

## Troubleshooting

| Issue | Solution |
|:---|:---|
| `sqlite3` ImportError | Install `pysqlite3-binary` |
| Neo4j Connection | Check `SMP_NEO4J_URI` and credentials in `.env` |
| SyntaxError | Use Python 3.11 |
| Enrichment Timeout | Set `SMP_ENRICHMENT=none` in `.env` |

---

## Contributing

1. Use `feature/` or `fix/` branches
2. Follow patterns in `AGENTS.md`
3. Add tests for new features
4. Run `ruff check . && ruff format . && mypy smp/ && pytest`

---

*SMP — Empowering agents with structural memory.*