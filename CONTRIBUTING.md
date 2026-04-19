Here is an expanded, standalone, and highly detailed `CONTRIBUTING.md` file. It goes deeper into the specific developer workflows, testing graph databases, adding protocol methods, and code standards required for the Structural Memory Protocol (SMP).

***

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
- **Docker** (Required for spawning agent sandboxes and running Testcontainers for DBs)
- **Neo4j Desktop** or Neo4j Docker image (Must include the **Graph Data Science (GDS)** plugin for Louvain and PageRank).

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
   *Note: Make sure `NEO4J_URI` points to an instance with the GDS plugin enabled.*

---

## 🧠 Mental Model & Architecture

Before writing code, please read the [ARCHITECTURE.md](ARCHITECTURE.md). 

**Key rules to remember:**
- **No LLMs at Query Time:** Do not add external API calls to OpenAI/Anthropic inside the query engine (`SeedWalkEngine`). Relevance is calculated via graph math (Vector + PageRank + HeatScore).
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
1. Update the schema documentation in `ARCHITECTURE.md`.
2. Update the `NodeTypes` or `EdgeTypes` Enums in `smp/core/constants.py`.
3. Add any required Neo4j index constraints in `smp/core/store.py` (e.g., `CREATE INDEX IF NOT EXISTS FOR (n:NewType) ON (n.id)`).

---

## 🧪 Testing Guidelines

We use **pytest** and `pytest-asyncio`. Graph databases and vector stores present unique testing challenges.

1. **Unit Tests:** Should mock Neo4j and ChromaDB. Use these for testing logic (e.g., ranking math in `SeedWalkEngine._rank`).
2. **Integration Tests:** Found in `tests/integration/`. These require actual databases. The CI pipeline uses Testcontainers to spin up ephemeral Neo4j and ChromaDB instances.
3. **Writing Cypher in Tests:** When testing Cypher queries, always clean up the graph state in a `finally` block or use a fresh database schema per test.

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
- Ensure your PR title matches the Conventional Commits format (e.g., `feat: implement eBPF trace extraction`).
- Wait for a maintainer (or a designated Reviewer Agent) to review your code!