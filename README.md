# Structural Memory Protocol (SMP)

**High-Fidelity Codebase Intelligence Made for AI to Handle Large Codebases Without Breaking**

Structural Memory Protocol (SMP) provides AI agents with a "programmer's brain." While traditional RAG treats code as flat text—often leading to context window overflow, hallucinations, and a loss of architectural context—SMP models code as a multi-dimensional graph of entities, relationships, and semantic meanings.

By combining structural graph analysis with vector-seeded discovery, SMP allows AI agents to navigate massive codebases with precision, perform deep impact analysis, and execute safe refactorings without losing sight of the big picture.

---

## 🚀 Key Features

*   **AI-First Architecture:** Specifically designed to prevent agents from "breaking" when facing 100k+ line codebases.
*   **MCP Native:** Fully supports the **Model Context Protocol (MCP)**, allowing SMP to act as a standardized memory layer for any MCP-compatible AI IDE or agent.
*   **Community-Routed Graph RAG:** Uses a hybrid approach—**ChromaDB** for high-speed seed discovery and **Neo4j** for structural traversal—to provide exact, context-aware results.
*   **Hybrid Linking:** Combines static AST analysis (Tree-sitter) with runtime execution traces (eBPF) to resolve dynamic dependencies that static analysis misses.
*   **Automatic Community Detection:** Partitions the codebase into structural clusters, allowing agents to reason about domain boundaries and architecture.
*   **Blast Radius Analysis:** Quantify the exact impact of a change before a single line of code is edited.

---

## 🛠 Quickstart

### 1. Docker Compose (Fastest)
```bash
git clone https://github.com/your-org/smp.git
cd smp
cp .env.example .env # Edit with your Neo4j password
docker compose up -d
curl http://localhost:8420/health # Returns: {"status":"ok"}
```

### 2. Manual Installation
**Requirements:** Python 3.11, Neo4j 5.x.

```bash
# Environment Setup
cp .env.example .env
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Start the Server
smp serve --port 8420
```

---

## 📐 How it Works: The "Programmer's Brain"

SMP replaces flat-text retrieval with a structured pipeline:

1.  **Ingestion:** Tree-sitter parses source code into an AST $\rightarrow$ Graph Builder creates entities (Classes, Functions) $\rightarrow$ Linker resolves `CALLS` and `IMPORTS` edges.
2.  **Enrichment:** Static metadata (docstrings, type annotations) is extracted and indexed.
3.  **Vector Seeding:** ChromaDB stores embeddings of function signatures and docstrings for initial "seed" discovery.
4.  **Graph Traversal:** From the seeds, the engine performs a multi-hop walk in Neo4j to capture the structural context surrounding the target code.
5.  **Routing:** Community detection (Louvain) routes queries to specific architectural modules, reducing noise and increasing precision.

---

## 💻 Usage

### Ingest and Query via CLI
```bash
# Ingest a project
smp ingest /path/to/your/project

# Query the intelligence layer
smp query "Where is the authentication logic handled?"
```

### Python SDK Example
```python
import asyncio
from smp.client import SMPClient

async def main():
    async with SMPClient("http://localhost:8420") as client:
        # Locate a feature using Community-Routed Graph RAG
        results = await client.locate("user registration flow")
        
        # Perform impact analysis
        impact = await client.assess_impact("src/auth/manager.py::authenticate")
        print(f"Change affects {impact['total_affected_nodes']} nodes")

asyncio.run(main())
```

---

## 📖 Documentation
- [Architecture Guide](ARCHITECTURE.md) - Deep dive into the Graph RAG pipeline.
- [API Reference](API.md) - JSON-RPC 2.0 specification.
- [User Guide](USER_GUIDE.md) - Tutorials and advanced workflows.
- [Contributing](CONTRIBUTING.md) - How to extend SMP.

---

*SMP — Giving AI agents the structural memory to master any codebase.*
