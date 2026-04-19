# AGENTS.md — Coding Agent Instructions for SMP

## Project Overview

SMP (Structural Memory Protocol) is a graph-based codebase intelligence system for AI agents.
It parses source code into a knowledge graph (Neo4j) with vector embeddings (ChromaDB),
exposing a JSON-RPC API via FastAPI.

**Stack:** Python 3.11+, FastAPI, msgspec, tree-sitter, Neo4j, ChromaDB, pytest.

**IMPORTANT:** This project requires **Python 3.11** explicitly. Always use `python3.11` or ensure your virtual environment is created with Python 3.11. The project uses 3.11+ features (`X | Y` unions, `tomllib`, etc.) and ruff/mypy are configured with `target-version = "py311"`.

---

## Build / Lint / Test Commands

```bash
# Create venv with Python 3.11
python3.11 -m venv .venv && source .venv/bin/activate

# Install in dev mode
pip install -e ".[dev]"

# Lint (check + format)
ruff check .
ruff format .

# Type check
mypy smp/

# Run all tests
pytest

# Run a single test file
pytest tests/test_models.py

# Run a single test class
pytest tests/test_models.py::TestGraphNode

# Run a single test method
pytest tests/test_models.py::TestGraphNode::test_defaults

# Run the server
python3.11 -m smp.cli serve

# Ingest a directory
python3.11 -m smp.cli ingest <directory>

# Run a command in background (returns immediately, agent continues working)
# IMPORTANT: Use full path to venv python3.11 so it can find the smp module
python3.11 -m smp.cli run <name> -- .venv/bin/python -m <module> [args...]
# Example: start server in background
python3.11 -m smp.cli run myserver -- .venv/bin/python -m smp.cli serve --port 8420

# List running background processes
python3.11 -m smp.cli ps

# View logs for a background process
python3.11 -m smp.cli logs <name>

# Stop a background process
python3.11 -m smp.cli stop <name>

# Restart a background process (use --restart flag when running)
python3.11 -m smp.cli run <name> -- .venv/bin/python -m <module> --restart
python3.11 -m smp.cli run <name> -- <command> --restart
```

Always run `ruff check .`, `ruff format .`, and `mypy smp/` after making changes.

---

## Code Style

### Imports

- Every file starts with `from __future__ import annotations`.
- Group imports: stdlib → third-party → local, separated by blank lines.
- Use absolute imports for local modules: `from smp.core.models import GraphNode`.
- Prefer `from X import Y` over `import X` for specific names.
- Use `list[...]`, `dict[...]`, `set[...]` (builtin generics), never `List`, `Dict`, `Set`.
- Use `X | Y` for unions (python3.11 3.11+), not `Optional[X]` or `Union[X, Y]`.

### Formatting

- Line length: 120 characters max.
- Formatting enforced by `ruff format` — no manual alignment or custom spacing.

### Naming

- **Modules:** `snake_case.py`
- **Classes:** `PascalCase` (e.g., `GraphNode`, `Neo4jGraphStore`)
- **Functions/methods:** `snake_case`
- **Constants:** `_UPPER_SNAKE_CASE` (leading underscore for module-private)
- **Private members:** `_leading_underscore`
- **Enums:** `PascalCase` class, `UPPER_SNAKE_CASE` members

### Type Annotations

- All function signatures must have full type annotations (enforced by mypy strict mode).
- `self` and `cls` annotations are not required (ANN101/ANN102 ignored).
- Avoid `Any` in return types (ANN401 ignored only when unavoidable).

### Docstrings

- Use triple double-quotes, imperative mood, Google style.
- Omit docstrings for trivial/private methods; prefer clear naming instead.

### Logging

- Use structured logging: `log = get_logger(__name__)`.
- Log with keyword context: `log.info("event_name", key=value)`.
- Never use f-strings in log calls; pass structured fields instead.

---

## Architecture & Patterns

- **Layered:** `core` (models) → `engine` (logic) → `protocol` (API) → `store` (persistence).
- **Interfaces:** Abstract base classes in `interfaces.py` files using `abc.ABC` + `@abc.abstractmethod`.
- **Models:** Use `msgspec.Struct`; prefer `frozen=True` for immutable data.
- **Dependency injection:** Pass dependencies via constructor parameters.
- **Factories:** Use `create_app()` style factory functions for complex setup.
- **Registry:** Use `ParserRegistry` pattern for lazy/dispatched initialization.
- **Async:** Use `async`/`await` throughout; async context managers via `__aenter__`/`__aexit__`.

---

## Testing

- Framework: **pytest** with **pytest-asyncio** (`asyncio_mode = "auto"`).
- Tests live in `tests/`, mirroring the source structure.
- Use fixtures from `conftest.py`: `clean_graph`, `vector_store`, `make_node()`, `make_edge()`.
- Group related tests in classes (e.g., `class TestGraphNode:`).
- Async tests: just define as `async def test_...` — the `@pytest.mark.asyncio` decorator is auto-applied.
- Prefer factory helpers over inline test data construction.

---

## Lint Rules (ruff)

Enabled rule sets: `E` (pycodestyle), `F` (pyflakes), `I` (isort), `N` (naming),
`UP` (pyupgrade), `B` (bugbear), `SIM` (simplify), `ANN` (annotations).

Ignored: `ANN101`, `ANN102`, `ANN401`.

---

## Pre-Commit Checklist

Before submitting changes:

1. `ruff check .` — no lint errors
2. `ruff format .` — code is formatted
3. `mypy smp/` — no type errors
4. `pytest` — all tests pass
