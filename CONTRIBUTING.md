

# Contributing to the Structural Memory Protocol (SMP)

First off, thank you for considering contributing to SMP! 🎉 

SMP is not a standard web application; it is the core memory and safety guardrail layer for autonomous AI agents. Because this codebase is read, parsed, and modified by both **humans** and **AI agents**, strict adherence to architectural consistency, immutability, and explicit typing is absolutely critical.

This guide will walk you through the setup, coding standards, and workflows required to contribute successfully.

---

## 📑 Table of Contents
1. [Development Environment Setup](#-development-environment-setup)
2. [Mental Model & Architecture](#-mental-model--architecture)
3. [Coding Standards](#-coding-standards)
4. [How to Add New Features](#-how-to-add-new-features)
5. [Testing Guidelines](#-testing-guidelines)
6. [Git & PR Workflow](#-git--pr-workflow)

---

## 🛠️ Development Environment Setup

### Prerequisites
- **Python 3.11+** (Strict requirement for `X | Y` unions, `tomllib`, and `msgspec` optimizations)
- **No external database** — the graph is a self-contained `.smpg` file (`MMapGraphStore`); vectors are
  optional bring-your-own embeddings (`.smpv`). No Neo4j, no ChromaDB.
- **Docker** (Optional — only for sandbox-related experiments, not required for tests)

### Installation
1. **Clone & Create a Virtual Environment:**
   ```bash
   git clone https://github.com/your-org/structural-memory.git
   cd structural-memory
   python3.11 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. **Install Dependencies in Editable Mode:**
   ```bash
   pip install -e ".[dev]"
   ```

3. **Configure the Environment:**
   Copy the example environment file and configure your database endpoints.
   ```bash
   cp .env.example .env
   ```
    *Note: `SMP_GRAPH_PATH` points at the `.smpg` graph file (default `.smp/graph.smpg`); `SMP_VECTOR_PATH`
    points at the optional `.smpv` vector file. There are no database credentials to configure.*

---

## 🧠 Mental Model & Architecture

Before writing code, please read the [ARCHITECTURE.md](ARCHITECTURE.md). 

**Key rules to remember:**
- **Keyword search only:** Do not add embedding generation, vector seeding, BM25, or PageRank/Louvain to the
  query engine. `smp/locate` / `smp/search` relevance is plain keyword scoring over names, docstrings,
  descriptions, tags, IDs, and file paths. Vectors are bring-your-own via `smp/vector/*` only.
- **Immutability First:** Data flowing through the system must be immutable. We use `msgspec.Struct` with `frozen=True`.
- **Agents are untrusted:** Any endpoint touching the filesystem must go through the Sandbox and `smp/guard/check`.

---

## 📝 Coding Standards

We use automated tools to enforce our standards, but here are the specific rules you must follow:

### 1. Type Annotations & Data Models
- **No `typing` module fallbacks:** Use modern Python 3.11+ syntax.
  - ❌ `Optional[str]`, `Union[int, str]`, `List[str]`, `Dict[str, Any]`
  - ✅ `str | None`, `int | str`, `list[str]`, `dict[str, Any]`
- **Msgspec Structs:** All data models must use `msgspec`. Do not use `dataclasses` or `pydantic` (they are too slow for massive graph serialization).
  ```python
  import msgspec

  class RankedResult(msgspec.Struct, frozen=True):
      node_id: str
      node_type: str
      vector_score: float
      is_seed: bool = False
  ```

### 2. Imports
- Every file must start with `from __future__ import annotations`.
- Always use **absolute imports** for local modules.
  - ❌ `from .models import WalkNode`
  - ✅ `from smp.engine.models import WalkNode`
- Group imports: `Standard Library` $\rightarrow$ `Third-Party` $\rightarrow$ `Local`. Separate groups with a blank line.

### 3. Naming Conventions & Docstrings
- **Classes:** `PascalCase`
- **Functions/Methods/Variables:** `snake_case`
- **Private Members:** Prefix with a single underscore `_private_method`.
- **Docstrings:** Use Google-style docstrings. Because SMP parses docstrings for the `smp/enrich` pipeline, docstrings must be clear, concise, and written in the imperative mood.

---

## 🔌 How to Add New Features

### Adding a New JSON-RPC Protocol Method
SMP does not use a massive `if/else` statement for protocol routing. We use a **Dispatcher Pattern**.

1. Locate the correct handler file in `smp/protocol/handlers/` (e.g., `query.py`, `safety.py`, `sandbox.py`).
2. Define your asynchronous handler function.
3. Decorate it with `@rpc_method("smp/your/method")`.
4. Define the input/output schema using `msgspec`.

**Example:**
```python
# smp/protocol/handlers/telemetry.py
from smp.protocol.dispatcher import rpc_method
from smp.core.models import ServerContext

@rpc_method("smp/telemetry/hot")
async def handle_telemetry_hot(params: dict, ctx: ServerContext) -> dict:
    """Retrieves high-churn, high-impact nodes."""
    window = params.get("window_days", 30)
    return await ctx.engine.telemetry.get_hot_nodes(window)
```

### Modifying the Graph Schema
If you add a new node type or relationship type (e.g., `IMPLEMENTS`):
1. Update the `NodeType` or `EdgeType` enums in `smp/core/models.py`.
2. Update the parser in `smp/store/graph/parser.py` if the new type needs AST extraction.
3. Add storage/query handling in `smp/store/graph/mmap_store.py` as needed.

---

## 🧪 Testing Guidelines

We use **pytest** and `pytest-asyncio`. The stores are self-contained files, so tests need no live services.

1. **Unit Tests:** Should use tmp-dir `MMapGraphStore` / `MMapVectorStore` fixtures from `tests/conftest.py`.
   Use mocks only for testing pure logic (e.g., keyword scoring in the query engine's `locate`/`search`).
2. **Integration Tests:** Found in `tests/`. These run against real `.smpg` / `.smpv` files in tmp dirs —
   no Testcontainers, no external databases.
3. **Graph state in Tests:** Always isolate per test via the `clean_graph` / `graph_store` fixtures (fresh tmp-dir
   store per test); never share a graph file between tests.

**Running Tests:**
```bash
# Run everything
pytest

# Run fast unit tests only (skips DB integration tests)
pytest -m "not integration"
```

---

## 🚀 Git & PR Workflow

### 1. Branching
Create a branch from `main` using the following convention:
- `feature/your-feature-name`
- `fix/issue-description`
- `docs/what-you-updated`

### 2. Committing (Conventional Commits)
Write meaningful commit messages based on the Conventional Commits specification:
- `feat: add AST data-flow verification`
- `fix: resolve static linker namespacing bug`
- `refactor: migrate dataclasses to msgspec`

### 3. The "Big 4" Pre-Commit Checks
Before opening a Pull Request, you **must** run and pass these four commands. CI will fail immediately if these are not met:

```bash
# 1. Linting (Ruff)
ruff check .

# 2. Formatting (Ruff)
ruff format .

# 3. Type Checking (Mypy - Strict Mode)
mypy smp/

# 4. Testing (Pytest)
pytest
```

### 4. Opening a Pull Request
- Push your branch to your fork.
- Open a PR against the `main` branch.
- Fill out the PR template provided in `.github/PULL_REQUEST_TEMPLATE.md`.
- Ensure your PR title matches the Conventional Commits format (e.g., `feat: add placeholder linking pass`).
- Wait for a maintainer (or a designated Reviewer Agent) to review your code!