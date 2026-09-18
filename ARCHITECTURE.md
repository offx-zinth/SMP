# Architecture Guide: Structural Memory Protocol (SMP)

The Structural Memory Protocol (SMP) provides AI agents with a "programmer's mental model" of a codebase. Unlike traditional Retrieval-Augmented Generation (RAG) which treats code as a series of text chunks, SMP treats code as a structured, queryable graph of interrelated entities. 

This document outlines the production architecture, ingestion pipeline, query engine, safety protocols, and implementation stack.

---

## 🎯 Architectural Principles
1. **Precision over Probability:** Replace "likely" text matches with exact structural relationships.
2. **Hybrid Truth:** Combine static analysis ("what the source says") with runtime eBPF telemetry ("what the kernel actually does").
3. **No LLMs at Query Time:** Structural mapping and relevance ranking are computed via graph topology and keyword
   scoring. There is no built-in embedding model: vector search uses caller-supplied embeddings only.
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
│  │  │ GRAPH STORE    │ │ VECTOR STORE   │ │ MERKLE INDEX  │ │   │
│  │  │ (mmap `.smpg`) │ │ (FAISS `.smpv`)│ │ (SHA-256)     │ │   │
│  │  │ Structure/Walk │ │ BYO embeddings │ │ Sync/Diffs    │ │   │
│  │  └────────────────┘ └────────────────┘ └───────────────┘ │   │
│  └──────────────────────────────┬───────────────────────────┘   │
└─────────────────────────────────┼───────────────────────────────┘
                                   │
           ┌───────────────────────┼───────────────────────┐
           ▼                       ▼                       ▼
┌─────────────────┐   ┌──────────────────────┐   ┌───────────────┐
│  QUERY ENGINE   │   │   SANDBOX RUNTIME    │   │  SWARM LAYER  │
│  Query Engine   │   │  Docker / MicroVM    │   │  Peer Review  │
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
The Graph Builder instantiates nodes in the memory-mapped journal graph store (`.smpg`). The linker then resolves
relationships to ensure graph accuracy.

* **Static Linking (same-file resolution at ingest):**
  Calls whose target is defined in the same file are resolved during ingest.
* **Global name-based placeholder resolution (`resolve_placeholders`):**
  Remaining calls are kept as `::name::` placeholders and linked by structural name across files and languages.
  This over-approximates (same-named functions may link together) — the safe direction for impact analysis.

### 3. Static Enricher
Extracts semantic metadata (docstrings, decorators, annotations) directly from the AST without LLMs. No embeddings are
generated: the FAISS-backed vector store (`.smpv`) holds only caller-supplied embeddings via `smp/vector/upsert`.

### 4. Community Detection
Partitions the graph into connected components over the selected relationship types for architectural overviews:
* **Level 0 (Coarse):** Architectural domains (e.g., `api_gateway`, `data_layer`).
* **Level 1 (Fine):** Functional modules (e.g., `auth_oauth`).

---

## 🔍 Part 2: The Query Engine

`smp/locate` and `smp/search` are keyword search over names, docstrings, descriptions, tags, IDs, and file paths —
no vector seeding, no PageRank. Results are ranked by keyword score:

1. **Match**
   Score terms against entity names (highest weight), IDs, docstrings, descriptions, tags, and file paths.
2. **Filter**
   Narrow by node type, tags, or scope (`smp/search`), or by field list and node types (`smp/locate`).
3. **Rank**
   Sort by descending score and return the top-K matches with `matched_on` provenance.
4. **Expand**
   Use `smp/navigate`, `smp/trace`, and `smp/context` to walk the structural graph from any match.

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
| **Graph store** | **mmap journal (`.smpg`)** | Structural truth: nodes, edges, sessions, locks, audit, telemetry. |
| **Vector store** | **FAISS over mmap (`.smpv`)** | BYO-embeddings via `smp/vector/*`; ingest creates none. |
| **Merkle Tree** | **In-memory/Graph** | SHA-256 leaf per file. Allows `O(log n)` syncs for agents/servers via `smp/sync`. |

---

## 📁 Part 5: Codebase Structure & Dispatcher Pattern

The codebase is organized into layered domains. The API layer utilizes a **Dispatcher Pattern** to map JSON-RPC strings to Python handlers dynamically.

```text
structural-memory/
├── smp/
│   ├── core/                  # AST, Linkers, Enricher, Community, Merkle, FAISS vectors
│   ├── engine/                # Query engine, graph navigators
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
To add a new endpoint, implement a plain async handler function in the appropriate module under `smp/protocol/handlers/`
and register it in the method map in `smp/protocol/server.py`:

```python
from smp.protocol.handlers import query as query_handlers

# server.py maps method names to plain async handler functions — no god-file if/elif chain.
# Example: handle smp/locate with keyword params (see LocateParams in smp/core/models.py)
result = await query_handlers.locate({"query": "auth login", "top_k": 5}, ctx)
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
    Copy `.env.example` to `.env` and set `SMP_GRAPH_PATH` / `SMP_VECTOR_PATH` if you keep the `.smpg` / `.smpv`
    files outside the default `.smp/` directory. No external database is required.

---

## 🏛️ Architecture TL;DR
Before contributing, review `ARCHITECTURE.md`. SMP uses a layered design:
- `core/`: AST parsing, Linking (Static + eBPF), Enrichment, and persistence mapping.
- `engine/`: Query resolution (keyword search, structural aggregations), context generation.
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

class LocateHit(msgspec.Struct, frozen=True):
    entity: str
    file: str
    matched_on: str
    docstring: str | None = None
    tags: list[str] = msgspec.field(default_factory=list)
```

### Naming & Style
- **Classes:** `PascalCase`
- **Functions/Methods:** `snake_case`
- **Private Members:** Prefix with `_leading_underscore`.
- **Docstrings:** Use triple double-quotes, imperative mood, and Google style. Docstrings are indexed by keyword
  search, so be descriptive.
- **Line Length:** Max 120 characters.

---

## 🔌 Adding Protocol Methods (The Dispatcher)

We do not use massive `if/elif` routers. If you are adding a new JSON-RPC endpoint to SMP, implement it in the
appropriate module under `smp/protocol/handlers/` and register it in the method map in `smp/protocol/server.py`.

```python
# smp/protocol/handlers/telemetry.py
from typing import Any

async def telemetry_hot(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle smp/telemetry/hot — degree report for a single node."""
    graph = ctx["graph"]
    node = await graph.get_node(params["node_id"])
    ...
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
pytest tests/store/graph/test_query.py
```

---

## ✅ Pre-Commit Checklist

Before submitting a Pull Request, ensure you have completed these steps. Pull Requests failing CI will not be reviewed.

1. [ ] Read `ARCHITECTURE.md` to ensure your change fits the architectural direction.
2. [ ] `ruff check .` — No lint errors.
3. [ ] `ruff format .` — Code is formatted.
4. [ ] `mypy smp/` — Zero type errors.
5. [ ] `pytest` — All tests pass, including mmap store and query engine integration tests.

For detailed agent-specific interactions and JSON-RPC payloads, refer to `PROTOCOL.md` spec.
```