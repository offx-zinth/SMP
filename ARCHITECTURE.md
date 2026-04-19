# Architecture Guide: Structural Memory Protocol (SMP)

The Structural Memory Protocol (SMP) provides AI agents with a "programmer's mental model" of a codebase. Unlike traditional Retrieval-Augmented Generation (RAG) which treats code as a series of text chunks, SMP treats code as a structured, queryable graph of interrelated entities. 

This document outlines the production architecture, ingestion pipeline, query engine, safety protocols, and implementation stack.

---

## 🎯 Architectural Principles
1. **Precision over Probability:** Replace "likely" text matches with exact structural relationships.
2. **Hybrid Truth:** Combine static analysis ("what the source says") with runtime eBPF telemetry ("what the kernel actually does").
3. **No LLMs at Query Time:** Structural mapping, community routing, and relevance ranking are computed via graph topology and embeddings generated at *index* time.
4. **Agent Safety by Design:** Agents must acquire MVCC sessions, pass integrity guards, and execute in sandboxes before touching the main codebase.

---

## 🏗️ System Overview

```text
┌─────────────────────────────────────────────────────────────────┐
│                     CODEBASE (Files + Git)                      │
└──────────────────────────┬──────────────────────────────────────┘
                            │ Updates (Watch / Agent Push / commit)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   MEMORY SERVER (SMP Core)                      │
│  ┌─────────────┐   ┌──────────────┐   ┌─────────────┐           │
│  │   PARSER    │──▶│ GRAPH BUILDER│──▶│  ENRICHER   │           │
│  │ (Tree-sitter│   │ + LINKER     │   │ (Static     │           │
│  │             │   │ (Static+eBPF)│   │  Metadata)  │           │
│  └─────────────┘   └──────────────┘   └──────┬──────┘           │
│                                              │                  │
│  ┌───────────────────────────────────────────▼──────────────┐   │
│  │                    MEMORY STORE                          │   │
│  │  ┌────────────────┐ ┌────────────────┐ ┌───────────────┐ │   │
│  │  │ GRAPH DB       │ │ VECTOR INDEX   │ │ MERKLE INDEX  │ │   │
│  │  │ (Neo4j)        │ │ (ChromaDB)     │ │ (SHA-256)     │ │   │
│  │  │ Structure/Walk │ │ Routing/Seeds  │ │ Sync/Diffs    │ │   │
│  │  └────────────────┘ └────────────────┘ └───────────────┘ │   │
│  └──────────────────────────────┬───────────────────────────┘   │
└─────────────────────────────────┼───────────────────────────────┘
                                   │
           ┌───────────────────────┼───────────────────────┐
           ▼                       ▼                       ▼
┌─────────────────┐   ┌──────────────────────┐   ┌───────────────┐
│  QUERY ENGINE   │   │   SANDBOX RUNTIME    │   │  SWARM LAYER  │
│  SeedWalkEngine │   │  Docker / MicroVM    │   │  Peer Review  │
│  Context / Diff │   │  eBPF trace capture  │   │  PR Handoff   │
└────────┬────────┘   └──────────┬───────────┘   └───────┬───────┘
          └───────────────────────┴───────────────────────┘
                                  │ JSON-RPC 2.0 Dispatcher
                                  ▼
         ┌─────────────────────────────────────────────┐
         │              AGENT LAYER                    │
         │   (Coder)       (Reviewer)    (Architect)   │
         └─────────────────────────────────────────────┘
```

---

## ⚙️ Part 1: The Ingestion Pipeline

The ingestion pipeline transforms raw source code into a queryable knowledge graph.

### 1. Parser (AST Extraction)
SMP uses **Tree-sitter** for fast, incremental parsing across multiple languages. It extracts high-level entities into strongly typed `msgspec.Struct` models:
- **Nodes:** Files, Classes, Functions, Variables, Interfaces.
- **Metadata:** Signatures, docstrings, decorators, complexity metrics.
- **Dependencies:** Imports and exports.

### 2. Graph Builder & The Linker
The Graph Builder instantiates nodes in Neo4j. Senthil's Global Linker then resolves relationships to ensure graph accuracy.

* **Static Linking (Namespaced Resolution):** 
  To avoid ambiguity (e.g., two files having a `save()` function), the Linker uses the calling file's `imports` as a namespace map. It traces calls to their exact origin file, producing `CALLS_STATIC` edges marked `resolved: true`.
* **Runtime Linking (eBPF Execution Traces):** 
  Static analysis misses Dependency Injection and Metaprogramming. The Runtime Linker spawns a sandbox, executes tests, and captures kernel-level function traces via **eBPF**. These generate `CALLS_RUNTIME` edges in the graph.

### 3. Static Enricher
Extracts semantic metadata (docstrings, decorators, annotations) directly from the AST without LLMs. Embeddings are generated **once at index time** by concatenating `signature + docstring` and are stored in ChromaDB.

### 4. Community Detection (Louvain)
Uses the Louvain Algorithm via Neo4j GDS to partition the graph into two levels:
* **Level 0 (Coarse):** Architectural domains (e.g., `api_gateway`, `data_layer`).
* **Level 1 (Fine):** Functional modules (e.g., `auth_oauth`). Used by the Query Engine to restrict vector searches to specific community partitions.

---

## 🔍 Part 2: The Query Engine (`SeedWalkEngine`)

`SeedWalkEngine` implements a 5-phase Community-Routed Graph RAG pipeline for the `smp/locate` protocol.

1. **Phase 0: Route**
   Compares the query embedding against Level-1 Community Centroids in ChromaDB. If confidence is high ($>0.65$), the search is routed to a specific sub-graph (~200 nodes), eliminating massive codebase noise.
2. **Phase 1: Seed**
   Performs a vector search in ChromaDB, scoped to the routed community, to find the Top-K starting nodes based on their code signatures.
3. **Phase 2: Walk**
   Executes a single multi-hop Cypher traversal from the seed nodes. Follows `CALLS_STATIC`, `CALLS_RUNTIME`, `IMPORTS`, and `DEFINES` to pull structural context.
4. **Phase 3: Rank**
   Nodes are ranked using a composite score without LLMs:
   $$Score = \alpha \cdot Vector + \beta \cdot NormalizedPageRank + \gamma \cdot HeatScore$$
5. **Phase 4: Assemble**
   Produces a ranked list of `RankedResult` objects and a `structural_map` (adjacency list) so the agent can visualize the execution chain.

---

## 🛡️ Part 3: Agent Safety & Concurrency

SMP is the guardrail layer between autonomous agents and the codebase. Agents cannot touch files without SMP's approval.

### 1. MVCC Sessions & Locks
Agents request sessions (`smp/session/open`) targeting a specific `commit_sha`. For swarms, SMP uses Multi-Version Concurrency Control (MVCC) where agents operate in parallel, isolated sandboxes. Sequential file locking is reserved for blocking operations like database migrations.

### 2. Pre-Flight Guards & Checkpoints
Before writing, `smp/guard/check` assesses the targeted node. If an agent tries to modify a high-complexity "Hot Node" with zero test coverage, SMP returns `red_alert` and blocks the write until the agent writes tests. Agents must execute `smp/dryrun` (structural impact assessment) and `smp/checkpoint` before committing.

### 3. Sandbox & Integrity Verification
Agent writes are executed in ephemeral Docker/Firecracker microVMs (`smp/sandbox/spawn`). The network egress is firewalled. Upon completion, SMP runs two integrity gates (`smp/verify/integrity`):
1. **AST Data-Flow Check:** Ensures the test file's AST actually passes the function's output to an `assert()`.
2. **Deterministic Mutation Testing:** Injects operator mutations (`<` to `>`). If tests still pass (surviving mutants), the gate fails and forces the agent to tighten its assertions.

---

## 💾 Part 4: Data Stores & Persistence

| Store | Technology | Purpose |
| :--- | :--- | :--- |
| **Graph DB** | **Neo4j** | Structural truth. Holds nodes, relationships (`CALLS_STATIC`, `CALLS_RUNTIME`), PageRank, BM25 text index, Sessions, and Telemetry. |
| **Vector DB** | **ChromaDB** | Entry point routing. Holds node embeddings and Community Centroids. Queried *only* for finding Phase 1 Seeds. |
| **Merkle Tree** | **In-memory/Graph** | SHA-256 leaf per file. Allows `O(log n)` syncs for agents/servers via `smp/sync`. |

---

## 📁 Part 5: Codebase Structure & Dispatcher Pattern

The codebase is organized into layered domains. The API layer utilizes a **Dispatcher Pattern** to map JSON-RPC strings to Python handlers dynamically.

```text
structural-memory/
├── smp/
│   ├── core/                  # AST, Linkers, Enricher, Community, Merkle, Chroma
│   ├── engine/                # SeedWalkEngine, Reasoner, Graph Navigators
│   ├── sandbox/               # MicroVM lifecycle, eBPF daemon, Mutation Tester
│   ├── protocol/
│   │   ├── dispatcher.py      # @rpc_method registry mapping
│   │   └── handlers/          # Implementation of protocol methods
│   │       ├── memory.py      # smp/update, smp/sync
│   │       ├── query.py       # smp/locate, smp/context
│   │       ├── safety.py      # smp/session/*, smp/guard/*
│   │       └── sandbox.py     # smp/sandbox/*
│   └── main.py                # Server initialization
```

### The Dispatcher Model
To add a new endpoint, developers do not modify a monolithic router. Instead, use the `@rpc_method` decorator in the appropriate handler file:

```python
from smp.protocol.dispatcher import rpc_method
from smp.engine.models import LocateResponse

@rpc_method("smp/locate")
async def handle_locate(params: dict, ctx: ServerContext) -> LocateResponse:
    return await ctx.engine.seed_walk.locate(
        query=params["query"],
        seed_k=params.get("seed_k", 3)
    )
```

---

### 2. `CONTRIBUTING.md`

```markdown
# Contributing to SMP

Thank you for contributing to the Structural Memory Protocol (SMP)! To maintain the integrity, safety, and high performance of this agentic architecture, we enforce strict guidelines. 

## 🛠 Development Environment

### Python Version
SMP requires **Python 3.11** explicitly. We heavily utilize modern features like `X | Y` unions, `tomllib`, and performance optimizations not present in older versions.

### Setup Instructions
1. **Create a Virtual Environment:**
   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate
   ```
2. **Install Dependencies:**
   ```bash
   pip install -e ".[dev]"
   ```
3. **Configure Environment:**
   Copy `.env.example` to `.env` and configure your Neo4j and ChromaDB credentials. Note that Neo4j requires the GDS (Graph Data Science) plugin for Louvain and PageRank calculations.

---

## 🏛️ Architecture TL;DR
Before contributing, review `ARCHITECTURE.md`. SMP uses a layered design:
- `core/`: AST parsing, Linking (Static + eBPF), Enrichment, and persistence mapping.
- `engine/`: Query resolution (`SeedWalkEngine`), structural aggregations, context generation.
- `sandbox/`: MicroVM/Docker isolation, eBPF telemetry capture, and Mutation Testing.
- `protocol/`: JSON-RPC 2.0 endpoints utilizing the Dispatcher pattern.

---

## 📝 Coding Standards

SMP is designed to be read by humans and navigated by AI agents. Predictability is paramount.

### Imports
- Every file must start with `from __future__ import annotations`.
- Group imports: `stdlib` $\rightarrow$ `third-party` $\rightarrow$ `local`, separated by blank lines.
- **Always use absolute imports** for local modules: 
  `from smp.core.linker import StaticLinker` (Never `from ..linker import StaticLinker`).

### Type Annotations & Data Models
- **Strict Typing:** All function signatures must have full type annotations. No implicit `Any`.
- **Modern Unions:** Use `X | Y` instead of `Optional[X]` or `Union[X, Y]`.
- **Built-in Generics:** Use `list[...]`, `dict[...]`, `set[...]` instead of the `typing` module equivalents.
- **Msgspec Structs:** All data flowing through the protocol and engine must be defined as `msgspec.Struct` classes with `frozen=True` to ensure zero-copy immutability and fast JSON serialization.

```python
import msgspec

class RankedResult(msgspec.Struct, frozen=True):
    node_id: str
    node_type: str
    vector_score: float
    pagerank: float
    is_seed: bool = False
```

### Naming & Style
- **Classes:** `PascalCase`
- **Functions/Methods:** `snake_case`
- **Private Members:** Prefix with `_leading_underscore`.
- **Docstrings:** Use triple double-quotes, imperative mood, and Google style. Docstrings are heavily relied upon by the Graph RAG engine, so be descriptive.
- **Line Length:** Max 120 characters.

---

## 🔌 Adding Protocol Methods (The Dispatcher)

We do not use massive `if/elif` routers. If you are adding a new JSON-RPC endpoint to SMP, implement it in the appropriate module under `smp/protocol/handlers/` and use the `@rpc_method` decorator.

```python
# smp/protocol/handlers/telemetry.py
from smp.protocol.dispatcher import rpc_method
from smp.core.models import ServerContext

@rpc_method("smp/telemetry/hot")
async def handle_telemetry_hot(params: dict, ctx: ServerContext) -> dict:
    """Returns nodes with high churn and high blast radius."""
    window = params.get("window_days", 30)
    return await ctx.engine.telemetry.get_hot_nodes(window)
```

---

## 🔄 Development Workflow

### Branching
- `feature/description` for new functionality.
- `fix/description` for bug fixes.
- `docs/description` for documentation updates.

### Linting & Formatting
We use **Ruff** to enforce formatting and linting rules.
```bash
# Check for lint errors
ruff check .

# Automatically format code
ruff format .
```

### Type Checking
We rely on strict type boundaries. Run **Mypy** before committing:
```bash
mypy smp/
```

### Testing
We use **pytest** combined with `pytest-asyncio` for all asynchronous graph engine tests.
```bash
# Run all tests
pytest

# Run a specific module
pytest tests/engine/test_seed_walk.py
```

---

## ✅ Pre-Commit Checklist

Before submitting a Pull Request, ensure you have completed these steps. Pull Requests failing CI will not be reviewed.

1. [ ] Read `ARCHITECTURE.md` to ensure your change fits the architectural direction.
2. [ ] `ruff check .` — No lint errors.
3. [ ] `ruff format .` — Code is formatted.
4. [ ] `mypy smp/` — Zero type errors.
5. [ ] `pytest` — All tests pass, including integration tests spanning Neo4j and ChromaDB.

For detailed agent-specific interactions and JSON-RPC payloads, refer to `PROTOCOL.md` spec.
```