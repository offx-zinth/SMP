# SMP Codebase Exploration Index

This document indexes all the exploration documents created for the SMP project.

## Quick Navigation

### For Quick Start
- **[QUICK_START_GUIDE.md](QUICK_START_GUIDE.md)** - Installation, first queries, common workflows
  - Setup with Docker or manual installation
  - First steps: ingest code, start server, run queries
  - Real code examples for each operation
  - Common workflows (refactoring, documentation, architecture understanding)
  - Troubleshooting guide

### For Understanding Project Structure
- **[PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)** - Complete project anatomy
  - Directory structure with purpose of each module
  - Core functionality overview
  - Available tools and handlers
  - Test structure and fixtures
  - Design patterns used
  - Development workflow

### For API Reference
- **[MCP_TOOLS_REFERENCE.md](MCP_TOOLS_REFERENCE.md)** - All 49+ MCP tools with examples
  - 7 Query & Navigation tools
  - 4 Advanced Query tools
  - 3 Memory & Update tools
  - 7 Enrichment & Annotation tools
  - 4 Community Detection tools
  - 4 Sync & Integrity tools
  - 11 Safety & Session tools
  - 3 Sandbox tools
  - 2 Coordination & Handoff tools
  - 4 Observability tools
  - Organized by use case
  - Quick parameter reference

### Official Documentation
- **[README.md](README.md)** - High-level overview and features
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Deep dive into design
- **[API.md](API.md)** - Detailed API specification
- **[MCP_SERVER.md](MCP_SERVER.md)** - MCP integration guide
- **[AGENTS.md](AGENTS.md)** - Agent development instructions
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - Contribution guidelines
- **[USER_GUIDE.md](USER_GUIDE.md)** - Detailed workflows

---

## Directory Structure Quick Reference

```
/home/bhagyarekhab/SMP/
├── smp/                          # Main source code (~9,111 lines)
│   ├── core/                     # Data models
│   │   ├── models.py             # GraphNode, GraphEdge, NodeType, EdgeType
│   │   ├── merkle.py             # Merkle tree indexing
│   │   └── background.py         # Background tasks
│   ├── engine/                   # Core logic
│   │   ├── query.py              # Query engine (7 methods)
│   │   ├── graph_builder.py      # Graph construction
│   │   ├── enricher.py           # Semantic enrichment
│   │   ├── community.py          # Community detection
│   │   ├── linker.py             # Cross-file resolution
│   │   ├── safety.py             # Agent safety
│   │   ├── sandbox.py            # Code execution
│   │   ├── seed_walk.py          # Graph RAG
│   │   └── interfaces.py         # Abstract contracts
│   ├── parser/                   # AST extraction
│   │   ├── base.py               # TreeSitterParser base
│   │   ├── python_parser.py      # Python support
│   │   ├── typescript_parser.py  # TypeScript support
│   │   └── registry.py           # Parser registry
│   ├── protocol/                 # API layer
│   │   ├── server.py             # FastAPI factory
│   │   ├── mcp.py                # MCP server
│   │   ├── dispatcher.py         # JSON-RPC dispatcher
│   │   └── handlers/             # 37 handler implementations
│   ├── sandbox/                  # Isolated execution
│   ├── store/                    # Persistence
│   │   ├── interfaces.py         # Store contracts
│   │   ├── chroma_store.py       # Vector store
│   │   └── graph/                # Graph stores
│   ├── agent.py                  # High-level API
│   ├── client.py                 # RPC client
│   ├── cli.py                    # CLI entry points
│   └── logging.py                # Structured logging
├── tests/                        # Comprehensive test suite
│   ├── conftest.py              # Shared fixtures
│   ├── test_*.py                # Unit & integration tests
│   └── test_integration_*.py    # Complex integration tests
├── PROJECT_STRUCTURE.md         # This exploration (complete anatomy)
├── MCP_TOOLS_REFERENCE.md       # This exploration (API reference)
├── QUICK_START_GUIDE.md         # This exploration (getting started)
└── [other docs]                 # Official documentation
```

---

## Key Modules at a Glance

### Parser Layer (`smp/parser/`)
**Extracts code structure into typed nodes and edges**
- Supports: Python, TypeScript/JavaScript
- Uses: tree-sitter for AST parsing
- Key class: `TreeSitterParser` (abstract base)
- Output: `Document` with nodes, edges, errors

### Engine Layer (`smp/engine/`)
**Core logic for understanding and querying code**
| Module | Purpose |
|--------|---------|
| `query.py` | 7 high-level queries (navigate, trace, context, impact, locate, search, flow) |
| `graph_builder.py` | Ingest documents, resolve edges, link files |
| `enricher.py` | Extract metadata (docstrings, comments, types) |
| `community.py` | Louvain community detection |
| `linker.py` | Static cross-file resolution |
| `runtime_linker.py` | eBPF execution traces |
| `safety.py` | MVCC sessions, locks, checkpoints |
| `seed_walk.py` | Vector + graph hybrid RAG |

### Store Layer (`smp/store/`)
**Persistence abstraction**
| Store | Implementation | Purpose |
|-------|----------------|---------|
| GraphStore | Neo4j | Nodes, edges, traversal |
| VectorStore | ChromaDB | Embeddings, semantic search |

### Protocol Layer (`smp/protocol/`)
**API exposure**
- **FastAPI** - JSON-RPC 2.0 server on port 8000
- **MCP** - Model Context Protocol for Claude/agents
- **37 Handlers** - One per JSON-RPC method

---

## 49+ Exposable MCP Tools

### By Category
| Category | Count | Tools |
|----------|-------|-------|
| Query & Navigation | 7 | navigate, trace, context, impact, locate, search, flow |
| Advanced Query | 4 | diff, plan, conflict, why |
| Memory & Update | 3 | update, batch_update, reindex |
| Enrichment | 7 | enrich, enrich/batch, enrich/stale, enrich/status, annotate, annotate/bulk, tag |
| Community | 4 | detect, list, get, boundaries |
| Safety & Sessions | 11 | session/open, session/close, guard/check, dryrun, checkpoint, rollback, lock, unlock, audit/get, integrity/verify, session/recover |
| Sandbox | 3 | spawn, execute, destroy |
| Sync & Integrity | 4 | sync, merkle/tree, merkle/export, merkle/import |
| Handoff | 2 | handoff/review, handoff/pr |
| Telemetry | 4 | telemetry, telemetry/hot, telemetry/node, telemetry/record |
| **TOTAL** | **49** | |

---

## Test Structure Quick Reference

```
tests/
├── conftest.py                           # Fixtures: neo4j_store, clean_graph, make_node(), etc.
├── test_models.py                        # Core data models
├── test_parser.py                        # Parser implementations
├── test_protocol.py                      # Protocol layer
├── test_query.py                         # Query engine
├── test_store.py                         # Store operations
├── test_client.py                        # RPC client
├── test_enricher.py                      # Enrichment
├── test_update.py                        # Memory updates
├── test_integration_parser_graph.py       # Parser → Graph
├── test_integration_protocol_handlers.py  # Handlers
├── test_integration_query_engine.py       # Query operations
├── test_integration_vector_store.py       # Vector store
├── test_integration_community.py          # Community detection
├── test_integration_merkle.py             # Merkle tree
├── test_integration_safety.py             # Safety layer
├── test_integration_sandbox.py            # Sandbox execution
├── practical_verification.py              # End-to-end workflows
└── test_codebase/                        # Test subject (small Python project)
```

**Running tests:**
```bash
pytest                           # All tests
pytest tests/test_query.py       # Single file
pytest -k "navigate" -v          # Pattern match
pytest --cov=smp                # With coverage
```

---

## Core Data Models

### Enumerations
```python
NodeType:     Repository, Package, File, Class, Function, Variable, Interface, Test, Config
EdgeType:     CONTAINS, IMPORTS, DEFINES, CALLS, CALLS_RUNTIME, INHERITS, IMPLEMENTS,
              DEPENDS_ON, TESTS, USES, REFERENCES
Language:     PYTHON, TYPESCRIPT, UNKNOWN
```

### Main Structs (msgspec.Struct)
```python
GraphNode(id, type, file_path, structural, semantic)
GraphEdge(source_id, target_id, type, metadata)
StructuralProperties(name, file, signature, start_line, end_line, complexity, lines, parameters)
SemanticProperties(status, docstring, description, decorators, tags, inline_comments, annotations)
Document(file_path, language, nodes, edges, errors)
```

---

## Development Workflow

### Setup
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### Before committing
```bash
ruff check .           # Lint
ruff format .          # Format
mypy smp/              # Type check
pytest                 # Tests
```

### Run services
```bash
python3.11 -m smp.cli serve              # JSON-RPC API
python3.11 -m smp.protocol.mcp           # MCP server
python3.11 -m smp.cli ingest <dir>       # Parse directory
```

---

## Important Files to Read First

1. **`smp/core/models.py`** - All data structures (350+ lines)
2. **`smp/engine/interfaces.py`** - Abstract contracts (156+ lines)
3. **`smp/protocol/handlers/base.py`** - Handler pattern
4. **`smp/protocol/handlers/query.py`** - Query handler examples (142 lines)
5. **`smp/engine/query.py`** - Query engine logic (817+ lines)
6. **`tests/conftest.py`** - Test fixtures and examples

---

## Quick Problem Solver

**"How do I..."**

| Task | Tool | Example |
|------|------|---------|
| Find a function | `smp/navigate` | `{"query": "login"}` |
| See who calls function X | `smp/trace` | Trace CALLS incoming |
| Know what to edit together | `smp/context` | Get edit scope |
| Know impact of delete | `smp/impact` | Find blast radius |
| Parse new file | `smp/update` | Ingest with content |
| Extract docstrings | `smp/enrich` | Generate metadata |
| Find undocumented code | `smp/locate` + `smp/enrich/status` | Filter + enrich |
| Understand architecture | `smp/community/detect` | Detect clusters |
| Edit safely | `smp/session/open` + `smp/lock` | Create session, lock |
| Preview changes | `smp/dryrun` | Simulate without commit |
| Verify integrity | `smp/integrity/verify` | Check consistency |

---

## Common Patterns

### Pattern 1: Safe Editing
1. `smp/session/open` - Start session
2. `smp/lock` - Lock nodes
3. `smp/dryrun` - Preview
4. `smp/checkpoint` - Save point
5. `smp/update` - Make changes
6. `smp/session/close` - Commit

### Pattern 2: Understanding Code
1. `smp/navigate` - Find entity
2. `smp/trace` - See dependencies
3. `smp/context` - Get surrounding code
4. `smp/impact` - Understand blast radius

### Pattern 3: Documentation
1. `smp/locate` - Find all functions
2. `smp/enrich` - Extract metadata
3. `smp/annotate` - Add descriptions
4. `smp/tag` - Add categories

### Pattern 4: Architecture Analysis
1. `smp/community/detect` - Find modules
2. `smp/community/list` - See structure
3. `smp/community/boundaries` - Find high-coupling
4. `smp/community/get` - Module details

---

## Resources

- **Code examples:** See test files (e.g., `tests/test_query.py`)
- **API details:** `smp/protocol/handlers/*.py`
- **Data structures:** `smp/core/models.py`
- **CLI entry points:** `smp/cli.py`
- **Type definitions:** Look for `@abc.abstractmethod` in `interfaces.py` files

---

## Next Steps

1. Read **[QUICK_START_GUIDE.md](QUICK_START_GUIDE.md)** to get up and running
2. Explore **[MCP_TOOLS_REFERENCE.md](MCP_TOOLS_REFERENCE.md)** for all available operations
3. Review **[PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)** for deep dive into modules
4. Check test files for working code examples
5. Start with a small codebase (test_codebase/ included)

