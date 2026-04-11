# Structural Memory Protocol (SMP)

**High-Fidelity Codebase Intelligence for AI Agents**

Structural Memory Protocol (SMP) is a sophisticated graph-based memory system designed to provide AI agents with a deep, structured understanding of complex codebases. Unlike traditional RAG (Retrieval-Augmented Generation) which often treats code as flat text, SMP models code as a multi-dimensional graph of entities, relationships, and semantic meanings.

Built with **Python 3.11**, **FastAPI**, **Neo4j**, and **ChromaDB**, SMP enables agents to perform precise code navigation, impact analysis, and safe refactoring.

---

## 🌟 Key Capabilities

*   **Graph-Augmented Retrieval:** Navigate beyond simple keyword search by following `CALLS`, `INHERITS`, and `IMPORTS` relationships.
*   **Semantic Localization:** Use vector embeddings to find relevant code sections based on high-level intent.
*   **Impact Assessment:** Determine the "blast radius" of a potential change before modifying a single line of code.
*   **Safety & Sandboxing:** Includes an optional safety layer with session management, dry-run simulations, and isolated execution environments.
*   **Multi-Language Support:** First-class support for Python and TypeScript/JavaScript via Tree-sitter integration.

---

## 📂 Project Architecture

```text
SMP/
├── smp/                        # Root Source Directory
│   ├── core/                   # Foundation & Shared Services
│   │   ├── models.py           # msgspec-based data structures (GraphNode, Edge, etc.)
│   │   ├── background.py       # Management for long-running background tasks
│   │   └── logging.py          # Structured JSON logging configuration
│   ├── engine/                 # Intelligence & Processing Layer
│   │   ├── graph_builder.py    # Logic for transforming ASTs into graph nodes
│   │   ├── query.py            # Orchestrator for graph and vector searches
│   │   ├── enricher.py         # Semantic enrichment via LLMs (Gemini integration)
│   │   └── safety.py           # Guardrails: Lock management and session tracking
│   ├── protocol/               # Communication Layer (JSON-RPC 2.0)
│   │   ├── server.py           # FastAPI application factory
│   │   ├── dispatcher.py       # RPC method routing logic
│   │   └── handlers/           # Modular implementations of API methods (Trace, Impact, Flow)
│   ├── store/                  # Persistence Layer
│   │   ├── graph/              # Neo4j implementation and Cypher query builders
│   │   └── vector/             # ChromaDB and No-Op vector store implementations
│   ├── parser/                 # Syntax Analysis
│   │   └── base.py             # Tree-sitter integration for Python and TypeScript
│   ├── sandbox/                # Execution Safety
│   │   └── executor.py         # Isolated process management for dry-runs
│   ├── cli.py                  # Unified CLI for ingestion, serving, and process control
│   └── client.py               # Async Python SDK for agent integration
├── tests/                      # Rigorous testing suite mirroring source structure
└── AGENTS.md                   # Specialized prompt injection for SMP-aware agents
```

---

## 🚀 Installation & Setup

### 1. Requirements
- **Python 3+** (Strictly required for union types and modern async features)
- **Neo4j 5.x** (Local instance )
- **ChromaDB** (Managed automatically, but requires modern SQLite)

### 2. Environment Configuration
Create a `.env` file in the root directory:
```bash

# Database Configuration
SMP_NEO4J_URI="bolt://localhost:7687"
SMP_NEO4J_USER="neo4j"
SMP_NEO4J_PASSWORD="your-secure-password"


```

### 3. Installation Steps
```bash
# Clone and enter the repo
git clone https://github.com/offx-zinth/smp.git
cd smp

# Create venv with Python 3.11
python3.11 -m venv .venv
source .venv/bin/activate

# Install with development dependencies
pip install -e ".[dev]"
```

---

## 🛠 Usage Guide

### Ingesting a Project
Before an agent can use SMP, the codebase must be indexed:
```bash
smp ingest /path/to/target/project --clear
```

### Running the API Server
Start the JSON-RPC server to allow agent access:
```bash
smp serve --port 8420 --safety
```

### Background Task Management
SMP includes a built-in runner for long-running background processes:
```bash
# Start a service in the background
smp run my-server -- .venv/bin/python -m smp.cli serve

# Monitor processes
smp ps
smp logs my-server
```

### Integration Example (Python SDK)
```python
import asyncio
from smp.client import SMPClient

async def analyze_codebase():
    async with SMPClient("http://localhost:8420") as client:
        # 1. Semantic Search
        findings = await client.locate("Where is the user authentication handled?")
        
        # 2. Trace Call Graph
        # Get the full execution flow starting from a specific function
        call_graph = await client.trace("smp/protocol/server.py::create_app", depth=5)
        
        # 3. Predict Impact
        # What happens if we change this class?
        impact = await client.assess_impact("smp/core/models.py::GraphNode")
        print(f"Blast radius: {impact['total_affected_nodes']} nodes")

if __name__ == "__main__":
    asyncio.run(analyze_codebase())
```

---

## 🧪 Development & Quality Control

We enforce strict typing and linting standards. All PRs must pass the following:

```bash
# Run the test suite
pytest

# Check for type errors (Strict Mode)
mypy smp/

# Lint and Auto-format
ruff check . --fix
ruff format .
```

---

## 🛠 Troubleshooting

| Problem | Likely Cause | Solution |
|:---|:---|:---|
| `ImportError: cannot import name 'sqlite3'` | Outdated system SQLite | In Linux, ensure `pysqlite3-binary` is installed; SMP will automatically swap the module. |
| `Neo4j Connection Error` | Bolt port mismatch | Ensure Neo4j is listening on `7687` and your credentials match the `.env`. |
| `SyntaxError` in source | Wrong Python Version | Ensure you are using `python3.11`. Check with `python3 --version`. |
| `Enrichment Timeout` | LLM Rate Limiting | Set `SMP_ENRICHMENT=none` to skip LLM-based semantic analysis during ingestion. |

---

## 📜 Contributing
1.  **Branching:** Use `feature/` or `fix/` prefixes.
2.  **Style:** Follow the patterns in `AGENTS.md`. Use absolute imports and `msgspec` for all new models.
3.  **Tests:** Add a corresponding test in `tests/` for every new feature.
4.  **Logging:** Use structured logging with `get_logger(__name__)`. Never use f-strings in logs.

---
*SMP — Empowering agents with structural memory.*
