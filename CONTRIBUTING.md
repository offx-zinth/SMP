# Contributing to SMP

Thank you for contributing to the Structural Memory Protocol! To maintain high code quality and architectural consistency, please follow these guidelines.

## 🛠 Development Environment

### Python Version
SMP requires **Python 3.11** explicitly. It uses features like `X | Y` unions and `tomllib` that are not available in older versions.

### Setup
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
   Copy `.env.example` to `.env` and configure your Neo4j credentials.

---

## 📝 Coding Standards

We enforce a strict a set of styles to ensure the codebase remains maintainable for both humans and AI agents.

### Imports
- Every file must start with `from __future__ import annotations`.
- Group imports: `stdlib` $\rightarrow$ `third-party` $\rightarrow$ `local`, separated by blank lines.
- Use absolute imports for local modules: `from smp.core.models import GraphNode`.

### Type Annotations
- **Strict Typing:** All function signatures must have full type annotations.
- **Modern Unions:** Use `X | Y` instead of `Optional[X]` or `Union[X, Y]`.
- **Built-in Generics:** Use `list[...]`, `dict[...]`, `set[...]` instead of `List`, `Dict`, `Set`.

### Naming & Style
- **Classes:** `PascalCase`
- **Functions/Methods:** `snake_case`
- **Private Members:** `_leading_underscore`
- **Docstrings:** Use triple double-quotes, imperative mood, and Google style.
- **Line Length:** Max 120 characters.

### Architectural Patterns
- **Layered Design:** `core` (models) $\rightarrow$ `engine` (logic) $\rightarrow$ `protocol` (API) $\rightarrow$ `store` (persistence).
- **Interfaces:** Use `abc.ABC` and `@abc.abstractmethod` for all store and parser interfaces.
- **Models:** Use `msgspec.Struct` for data models; prefer `frozen=True` for immutability.

---

## 🔄 Development Workflow

### Branching
- Use `feature/description` for new functionality.
- Use `fix/description` for bug fixes.

### Linting & Formatting
We use **Ruff** for both linting and formatting.
```bash
# Check for lint errors
ruff check .

# Automatically format code
ruff format .
```

### Type Checking
We use **Mypy** in strict mode.
```bash
mypy smp/
```

### Testing
We use **pytest** with `pytest-asyncio`.
```bash
# Run all tests
pytest

# Run a specific test file
pytest tests/test_query.py
```

---

## ✅ Pre-Commit Checklist

Before submitting a Pull Request, ensure you have completed these four steps:
1. [ ] `ruff check .` — No lint errors.
2. [ ] `ruff format .` — Code is perfectly formatted.
3. [ ] `mypy smp/` — No type errors.
4. [ ] `pytest` — All tests pass.

For detailed agent-specific instructions, please refer to `AGENTS.md`.
