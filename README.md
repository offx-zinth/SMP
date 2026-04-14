# Structural Memory Protocol (SMP)

**High-Fidelity Codebase Intelligence for AI Agents**

---

SMP (Structural Memory Protocol) is a graph-based memory system that provides AI agents with a deep, structured understanding of complex codebases. Unlike RAG which treats code as flat text, SMP models code as a multi-dimensional graph of entities, relationships, and semantic meanings.

**Version:** 1.3.0 | **Stack:** Python 3.11+, FastAPI, Neo4j, ChromaDB

---

## Quickstart (Docker Compose)

```bash
git clone https://github.com/offx-zinth/smp.git
cd smp
cp .env.example .env
# Edit .env with your Neo4j password

docker compose up -d
curl http://localhost:8420/health
# Returns: {"status":"ok"}
```

---

## Quickstart (Manual)

### 1. Requirements
- **Python 3.11+**
- **Neo4j 5.x** (Local or AuraDB)
- **uv** (recommended) or pip

### 2. Environment
```bash
# Copy the example and configure
cp .env.example .env

# Edit .env with your credentials:
#   SMP_NEO4J_PASSWORD=your_neo4j_password
```

### 3. Install & Run
```bash
git clone https://github.com/offx-zinth/smp.git
cd smp

# Create venv with Python 3.11
python3.11 -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Start the server
smp serve
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     CODEBASE (Files + Git)                      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Updates (Watch / Agent Push / commit_sha)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   MEMORY SERVER (SMP Core)                      │
│  ┌─────────────┐   ┌──────────────┐   ┌─────────────┐           │
│  │   PARSER    │──▶│ GRAPH BUILDER│──▶│  ENRICHER   │           │
│  │ (AST/Tree-  │   │ + LINKER     │   │ (Static     │           │
│  │  sitter)    │   │ (Static +    │   │  Metadata)  │           │
│  │             │   │  eBPF Runtime│   │             │           │
│  └─────────────┘   └──────────────┘   └──────┬──────┘           │
│                                              │                  │
│  ┌───────────────────────────────────────────▼──────────────┐   │
│  │                    MEMORY STORE                          │   │
│  │                                                          │   │
│  │  ┌─────────────────────────────────────┐                 │   │
│  │  │  GRAPH DB (Neo4j)                   │                 │   │
│  │  │  Structure · CALLS_STATIC           │                 │   │
│  │  │  CALLS_RUNTIME · PageRank           │                 │   │
│  │  │  Sessions · Audit · Telemetry       │                 │   │
│  │  │  Full-Text Index (BM25)             │                 │   │
│  │  └─────────────────────────────────────┘                 │   │
│  │                                                          │   │
│  │  ┌─────────────────────────────────────┐                 │   │
│  │  │  VECTOR INDEX (ChromaDB)            │                 │   │
│  │  │  code_embedding per node            │                 │   │
│  │  │  community centroid embeddings      │                 │   │
│  │  └─────────────────────────────────────┘                 │   │
│  │                                                          │   │
│  │  ┌─────────────────────────────────────┐                 │   │
│  │  │  MERKLE INDEX                       │                 │   │
│  │  │  SHA-256 leaf per file node         │                 │   │
│  │  │  O(log n) sync & diff               │                 │   │
│  │  └─────────────────────────────────────┘                 │   │
│  └──────────────────────┬───────────────────────────────────┘   │
└─────────────────────────┼───────────────────────────────────────┘
                          │
       ┌───────────────────────┬───────────────┐
       │                       │               │
       ▼                       ▼               ▼
┌─────────────────┐   ┌──────────────────────┐   ┌───────────────┐
│  QUERY ENGINE   │   │   SANDBOX RUNTIME    │   │  SWARM LAYER  │
│  Navigator      │   │  Ephemeral microVM/  │   │  Peer Review  │
│  Reasoner       │   │  Docker + CoW fork   │   │  PR Handoff   │
│  SeedWalkEngine │   │  eBPF trace capture  │   │               │
│  Telemetry      │   │  Egress-firewalled   │   └───────┬───────┘
│  Community      │   │  Mutation Testing    │           │
└────────┬────────┘   └──────────┬───────────┘           │
         └──────────────┬────────┘               ────────┘
                        │ SMP Protocol (Dispatcher)
                        ▼
        ┌─────────────────────────────────────────────┐
        │              AGENT LAYER                    │
        │   Agent A       Agent B       Agent C       │
        │   (Coder)       (Reviewer)    (Architect)   │
        └─────────────────────────────────────────────┘
```

---

## Key Features

### Memory Store

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Graph DB** | Neo4j | Structure, CALLS, IMPORTS, PageRank, Sessions |
| **Vector Index** | ChromaDB | code_embedding, community centroids |
| **Merkle Index** | SHA-256 | O(log n) sync, state tracking |

### Query Engine

| Method | Description |
|--------|------------|
| `smp/navigate` | Find specific entities |
| `smp/trace` | Follow relationships |
| `smp/context` | Get relevant context (with role classification) |
| `smp/impact` | Assess change impact |
| `smp/locate` | SeedWalkEngine - Community-routed graph RAG |
| `smp/search` | BM25 full-text search |
| `smp/flow` | Trace data/logic path |

### Community Detection

- **Louvain Algorithm** at two resolutions (L0: coarse, L1: fine)
- **Centroid embeddings** for Phase 0 routing
- **Bridge detection** for cross-community coupling

### Agent Safety Protocol

| Method | Description |
|--------|------------|
| `smp/session/open` | Open agent session |
| `smp/session/close` | Close and persist |
| `smp/session/recover` | Resume session |
| `smp/lock` | Exclusive file lock |
| `smp/unlock` | Release lock |
| `smp/guard/check` | Pre-flight safety |
| `smp/dryrun` | Simulate changes |
| `smp/checkpoint` | Snapshot state |
| `smp/rollback` | Restore checkpoint |
| `smp/verify/integrity` | Mutation testing |
| `smp/audit` | Event logging |

### Sandbox Runtime

| Component | Description |
|-----------|------------|
| `smp/sandbox/spawn` | Create isolated environment |
| `smp/sandbox/execute` | Run code in sandbox |
| `smp/sandbox/destroy` | Cleanup |
| **DockerSandbox** | Container with CoW filesystem |
| **EBPFCollector** | Runtime trace capture |

### Swarm Handoff

| Method | Description |
|--------|------------|
| `smp/handoff/review` | Create peer review |
| `smp/handoff/pr` | Generate PR |

---

## Integration Tests

The SMP codebase includes comprehensive integration tests covering all major components:

```bash
# Run all integration tests
pytest tests/test_integration_*.py -v

# Results: 163 passed, 5 skipped
```

| Test Suite | Tests | Status |
|-----------|-------|--------|
| Query Engine | 34 | ✅ Pass |
| Agent Safety | 42 | ✅ Pass |
| Community Detection | 20 | ✅ Pass |
| Merkle Index | 16 | ✅ Pass |
| Vector Store | 29 | ✅ Pass |
| Protocol Handlers | 21 | ✅ Pass |
| Sandbox (Directory) | 22 | ✅ Pass |

### Tested Components

- **Parser + Graph Builder**: Extracts nodes and creates CALLS/IMPORTS/DEFINES edges
- **Query Engine**: navigate, trace, locate (SeedWalkEngine), get_context, assess_impact, find_flow
- **Safety**: Session management, locking, guards, dry runs, checkpoints, audit logging
- **Community**: Louvain L0/L1 detection, bridge detection, centroid computation
- **Merkle**: Tree build, hash, diff, sync, export/import
- **Vector Store**: ChromaDB upsert/query/delete with metadata filtering
- **Protocol**: All JSON-RPC methods registered and instantiatable

---

## Demo: JSON-RPC Query

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
    "self": {...},
    "imports": [...],
    "imported_by": [...],
    "defines": [...],
    "entry_points": [...],
    "data_flow_in": [...],
    "data_flow_out": [...],
    "summary": {
      "role": "core_utility",
      "blast_radius": 42,
      "avg_complexity": 3.2,
      "risk_level": "medium"
    }
  },
  "id": 1
}
```

---

## Python SDK

```python
import asyncio
from smp.client import SMPClient

async def main():
    async with SMPClient("http://localhost:8420") as client:
        # Graph RAG (SeedWalkEngine)
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
pytest tests/

# Integration tests
pytest tests/test_integration_*.py
```

---

## Troubleshooting

| Issue | Solution |
|:---|:---|
| `sqlite3` ImportError | Install `pysqlite3-binary` (automatically handled) |
| Neo4j Connection | Check `SMP_NEO4J_URI` and credentials in `.env` |
| ChromaDB errors | Ensure sqlite3 >= 3.35.0 or use pysqlite3 |
| Docker sandbox | Run with appropriate socket permissions |

---

## Project Structure

```
smp/
├── smp/
│   ├── core/            # Models, Merkle index, logging
│   ├── engine/         # Query, enricher, linker, safety
│   │               # community, seed_walk, pagerank
│   ├── protocol/      # JSON-RPC 2.0 API
│   │   └── handlers/ # Modular method handlers
│   ├── store/         # Neo4j, ChromaDB interfaces
│   ├── parser/        # Tree-sitter parsing
│   ├── sandbox/       # Docker, eBPF collector
│   ├── cli.py         # CLI
│   └── client.py      # Python SDK
├── tests/
│   ├── fixtures/        # Sample projects
│   └── test_integration_*.py  # Integration tests
├── .env.example
├── pyproject.toml
└── README.md
```

---

*SMP — Empowering agents with structural memory.*