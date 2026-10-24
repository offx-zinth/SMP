# SMP Project Structure Exploration Summary

## Overview
**SMP (Structural Memory Protocol)** is a graph-based codebase intelligence system that provides AI agents with
a programmer's brain instead of flat-text retrieval. It's built on Python 3.11+, FastAPI, msgspec, tree-sitter,
and FAISS — self-contained, with no external database.

- **Total Python Code:** ~9,111 lines
- **Stack:** Python 3.11+, FastAPI, msgspec, tree-sitter, FAISS, pytest
- **Protocol:** JSON-RPC 2.0 over FastAPI + MCP (Model Context Protocol)

---

## 1. Main Source Code Organization (`/smp` directory)

### Directory Structure
```
smp/
├── cli.py               # CLI: ingest | serve | mcp | backup | restore | compact | integrity
├── logging.py           # Structured logging
├── core/                # Data models and runtime config
│   ├── models.py        # GraphNode, GraphEdge, NodeType, EdgeType, method params (msgspec structs)
│   └── config.py        # Settings from env (SMP_GRAPH_PATH, SMP_VECTOR_PATH, SMP_HOST/PORT)
├── engine/              # Core processing logic
│   ├── query.py         # Query engine (navigate, trace, context, impact, locate, search, flow)
│   └── graph_builder.py # Graph ingestion and edge resolution
├── protocol/            # API layer
│   ├── server.py        # FastAPI app: JSON-RPC over HTTP (~50 smp/* methods)
│   ├── mcp.py           # MCP server over stdio
│   ├── auth.py          # API key auth + scopes
│   └── handlers/        # query, memory, enrichment, community, session, vector, sandbox, ...
├── runtime/             # Process execution
│   ├── sandbox.py       # Child-process sandbox runtime (private work dir, allowlist)
│   └── git_provider.py  # Git integration
├── store/               # Persistence layer (self-contained, no external DB)
│   ├── interfaces.py    # Abstract store interfaces
│   └── graph/           # Memory-mapped journal graph store (.smpg)
│       ├── mmap_store.py # MMapGraphStore + resolve_placeholders
│       ├── parser.py    # Tree-sitter structural parsing (14 languages)
│       ├── query.py     # Graph queries
│       └── journal.py   # Append-only journal
├── vector/              # FAISS-backed mmap vector store (.smpv, bring-your-own embeddings)
│   ├── mmap_vector.py
│   └── faiss_index.py
├── observability/
│   ├── backup.py        # backup/restore/compact (gzipped tarball + manifest.json)
│   └── metrics.py       # Metrics + telemetry
├── __init__.py          # Package init
```

---

## 2. Core Functionality and Tools

### 2.1 Parser Layer (`smp/store/graph/parser.py`)
**Purpose:** Extract code structure (functions, classes, interfaces, calls) into typed nodes and edge candidates
using tree-sitter AST analysis

**Key Classes:**
- `CodeParser` - Table-driven parser over `_LANGUAGE_SPECS`, plus a dedicated Python walker
- `LanguageSpec` - Per-language tree-sitter shapes (functions, classes, interfaces, calls)
- `ParsedFile` / `ParsedNode` / `EdgeCandidate` - Parse output consumed by the graph store

**Supported Languages (14):**
- Python (.py, .pyw, .pyi)
- JavaScript (.js, .jsx, .mjs, .cjs)
- TypeScript (.ts, .mts, .cts) and TSX (.tsx)
- Java, C (.c, .h), C++ (.cpp, .cc, .cxx, .hpp, .hh), C# (.cs)
- Go, Rust, PHP, Ruby, Swift, Kotlin (.kt, .kts), MATLAB (.m)

**Output:** `ParsedFile` with nodes, edge candidates (same-file calls resolved, rest as `::name::` placeholders),
and content hash

---

### 2.2 Engine Layer (`smp/engine/`)

#### Graph Building
**DefaultGraphBuilder** - Maps parsed documents to graph store
- Ingest documents with automatic edge resolution
- Handle cross-file references via import tracking
- Global linking for namespaced entities

#### Query Engine
**DefaultQueryEngine** provides high-level structural queries:
- `navigate()` - Find entity and its relationships
- `trace()` - Follow relationship chains (e.g., CALLS, IMPORTS)
- `get_context()` - Aggregate surrounding context for safe editing
- `assess_impact()` - Find blast radius of changes
- `locate()` - Keyword search ranked by match quality
- `search()` - Token/keyword search across metadata
- `find_flow()` - Trace execution/data flow paths

#### Enrichment
**StaticSemanticEnricher** generates metadata:
- Docstring extraction
- Inline comment collection
- Decorator identification
- Type annotation parsing
- Tag management
- Source hash computation

#### Linking
**Same-file resolution at ingest + global placeholder linking** (`resolve_placeholders`): cross-file calls are
recorded as `::name::` placeholder edges, then linked to every node with a matching structural name — across
files AND languages. This over-approximates (safe for impact analysis; same-named functions may link together).

#### Advanced Features
- **Community Detection** - Connected-component clustering over the call/import graph
- **Keyword Search** - `smp/locate` / `smp/search` score names, docstrings, descriptions, tags, IDs, file paths
- **Vector Store (BYO)** - FAISS-backed mmap store (`.smpv`); embeddings supplied via `smp/vector/upsert` only —
  ingest creates none and SMP ships no embedding model
- **Safety Layer** - Sessions, locks, dry-run simulation, checkpoints, audit log
- **Merkle Indexing** - O(log n) incremental sync

---

### 2.3 Store Layer (`smp/store/` + `smp/vector/`)

#### GraphStore (`smp/store/graph/mmap_store.py`)
Memory-mapped journal graph store (`.smpg` files) — self-contained, no external DB:

**Node Operations:**
- `upsert_node()`, `upsert_nodes()` - Insert/update
- `get_node()` - Retrieve by ID
- `delete_node()`, `delete_nodes_by_file()`
- `find_nodes()` - Query by properties

**Edge Operations:**
- `upsert_edge()`, `upsert_edges()`
- `get_edges()` - Directional retrieval

**Traversal:**
- `get_neighbors()` - N-hop traversal
- `traverse()` - BFS with edge type filtering

#### VectorStore (`smp/vector/mmap_vector.py`)
FAISS-backed mmap vector store (`.smpv` files) — bring-your-own embeddings only:
- `upsert()` - Store caller-supplied vectors + metadata (via `smp/vector/upsert`)
- `query()` / `search()` - Similarity search over stored vectors (via `smp/vector/search`)
- `delete()` - Tombstone vectors (via `smp/vector/delete`)

---

### 2.4 Core Models (`smp/core/models.py`)

**Enumerations:**
```python
NodeType:   Repository, Package, File, Class, Function, Variable, Interface, Test, Config
EdgeType:   CONTAINS, IMPORTS, DEFINES, CALLS, CALLS_RUNTIME, INHERITS, IMPLEMENTS, 
            DEPENDS_ON, TESTS, USES, REFERENCES
Language:   PYTHON, TYPESCRIPT, UNKNOWN
```

**Data Structures (msgspec.Struct):**
- `GraphNode` - Code entity with structural + semantic metadata
- `GraphEdge` - Directed relationship between nodes
- `StructuralProperties` - Coordinates, signature, complexity
- `SemanticProperties` - Docstring, comments, decorators, tags
- `Document` - Parsed file output
- `ParseError` - Syntax/extraction errors

---

## 3. Available API/Tools That Can Be Exposed as MCP Tools

### 3.1 Protocol Handlers (37 handlers in `smp/protocol/handlers/`)

The SMP API is built on **JSON-RPC 2.0** with handler classes implementing specific methods.

#### Query Handlers (7 tools)
```
smp/navigate      → NavigateHandler      - Find entity + relationships
smp/trace         → TraceHandler         - Follow dependency chains
smp/context       → ContextHandler       - Get contextual scope
smp/impact        → ImpactHandler        - Assess change blast radius
smp/locate        → LocateHandler        - Find code entities
smp/search        → SearchHandler        - Keyword search
smp/flow          → FlowHandler          - Find execution paths
```

#### Enrichment & Annotation (7 tools)
```
smp/enrich                → EnrichHandler           - Enrich single node
smp/enrich/batch          → EnrichBatchHandler      - Batch enrichment
smp/enrich/stale          → EnrichStaleHandler      - Find stale nodes
smp/enrich/status         → EnrichStatusHandler     - Enrichment coverage
smp/annotate              → AnnotateHandler         - Manually annotate
smp/annotate/bulk         → AnnotateBulkHandler     - Bulk annotation
smp/tag                   → TagHandler              - Add/remove tags
```

#### Memory Management (3 tools)
```
smp/update                → UpdateHandler           - Update single file
smp/batch_update          → BatchUpdateHandler      - Multiple file updates
smp/reindex               → ReindexHandler          - Reindex graph
```

#### Community Detection (4 tools)
```
smp/community/detect      → CommunityDetectHandler  - Run detection
smp/community/list        → CommunityListHandler    - List communities
smp/community/get         → CommunityGetHandler     - Get community details
smp/community/boundaries  → CommunityBoundariesHandler - Get boundaries
```

#### Agent Safety (11 tools)
```
smp/session/open          → SessionOpenHandler      - Create session
smp/session/close         → SessionCloseHandler     - Close session
smp/session/recover       → SessionRecoverHandler   - Recover session
smp/guard/check           → GuardCheckHandler       - Check guards
smp/dryrun                → DryRunHandler           - Simulate change
smp/checkpoint            → CheckpointHandler       - Create checkpoint
smp/rollback              → RollbackHandler         - Restore checkpoint
smp/lock                  → LockHandler             - Lock nodes
smp/unlock                → UnlockHandler           - Unlock nodes
smp/audit/get             → AuditGetHandler         - Get audit logs
smp/integrity/verify      → IntegrityVerifyHandler  - Verify integrity
```

#### Sandbox (3 tools)
```
smp/sandbox/spawn         → SandboxSpawnHandler     - Create sandbox
smp/sandbox/execute       → SandboxExecuteHandler   - Execute in sandbox
smp/sandbox/destroy       → SandboxDestroyHandler   - Destroy sandbox
```

#### Synchronization & Integrity (4 tools)
```
smp/sync                  → SyncHandler             - Merkle tree sync
smp/merkle/tree           → MerkleTreeHandler       - Get tree structure
smp/merkle/export         → IndexExportHandler      - Export index
smp/merkle/import         → IndexImportHandler      - Import index
```

#### Handoff & Coordination (2 tools)
```
smp/handoff/review        → HandoffReviewHandler    - Create review
smp/handoff/pr            → HandoffPRHandler        - Create pull request
```

#### Telemetry & Observability (4 tools)
```
smp/telemetry             → TelemetryHandler        - General telemetry
smp/telemetry/hot         → TelemetryHotHandler     - Hot paths
smp/telemetry/node        → TelemetryNodeHandler    - Node metrics
smp/telemetry/record      → TelemetryRecordHandler  - Record event
```

#### Advanced Query Extensions (4 tools - query_ext)
```
smp/diff                  → DiffHandler             - Diff analysis
smp/plan                  → PlanHandler             - Plan changes
smp/conflict              → ConflictHandler         - Conflict detection
smp/why                   → WhyHandler              - Explain relationships
```

---

### 3.2 MCP Server Implementation (`smp/protocol/mcp.py`)

Already implements MCP server with FastMCP wrapper:

**Features:**
- 36+ tools exposed as MCP tools
- Resources: `smp://stats`, `smp://health`
- Lifecycle management for graph/vector stores
- Safety layer initialization

**MCP Tool Categories:**
1. **Graph Intelligence** (8) - navigate, trace, context, impact, locate, search, flow, why
2. **Memory & Enrichment** (10) - update, batch_update, enrich, annotate, tag
3. **Safety & Integrity** (10) - sessions, guards, dry-run, checkpoints, locks, audit
4. **Execution & Sandbox** (3) - spawn, execute, destroy
5. **Coordination** (5) - handoff, PR, telemetry

---

## 4. Test Structure

### 4.1 Test Organization
```
tests/
├── conftest.py                              # Shared fixtures
├── fixtures/                                # Test data
├── test_codebase/                           # Test subject (small codebase)
│   ├── api/
│   ├── auth/
│   ├── db/
│   ├── utils/
│   ├── calculator.py
│   ├── __init__.py
│   ├── main.py
│   └── math_utils.py
├── test_models.py                           # Core model tests
├── test_parser.py                           # Parser tests
├── test_protocol.py                         # Protocol tests
├── test_query.py                            # Query engine tests
├── test_store.py                            # Store tests
├── test_client.py                           # Client tests
├── test_enricher.py                         # Enrichment tests
├── test_update.py                           # Update tests
├── test_integration_parser_graph.py          # Parser → Graph integration
├── test_integration_protocol_handlers.py     # Handler integration
├── test_integration_query_engine.py          # Query engine integration
├── test_integration_vector_store.py          # Vector store integration
├── test_integration_community.py             # Community detection
├── test_integration_merkle.py                # Merkle tree
├── test_integration_safety.py                # Safety layer
├── test_integration_sandbox.py               # Sandbox
├── practical_verification.py                # End-to-end scenarios
└── results/                                 # Test result artifacts
```

### 4.2 Test Framework & Fixtures
- **Framework:** pytest + pytest-asyncio
- **Async Mode:** auto (no decorator needed)
- **Fixtures in conftest.py:**
  - `graph_store` - Fresh `MMapGraphStore` in a tmp dir (per test)
  - `clean_graph` - Per-test fresh graph with cleanup
  - `make_node()` - Factory for test nodes
  - `make_edge()` - Factory for test edges
  - `vector_store` - `MMapVectorStore` fixture in a tmp dir
  - `populated_graph_store` / `populated_vector_store` - Pre-filled fixtures

### 4.3 Test Coverage Areas
1. **Unit Tests** - Models, parsers, individual components
2. **Integration Tests** - Parser→Graph, Query→Store, Handler→Engine
3. **Practical Tests** - End-to-end workflows with real codebase
4. **Fixtures** - Sample Python/TypeScript projects for testing

### 4.4 Running Tests
```bash
pytest                              # Run all tests
pytest tests/test_models.py         # Single file
pytest tests/test_models.py::TestGraphNode  # Single class
pytest tests/test_models.py::TestGraphNode::test_defaults  # Single method
pytest -k "query" -v                # Filter by pattern
pytest --asyncio-mode=auto          # Explicit async mode
```

---

## 5. Key Design Patterns

### 5.1 Architecture Layers
```
Protocol Layer (handlers) → Engine Layer (logic) → Store Layer (persistence)
      ↓                          ↓                         ↓
JSON-RPC 2.0              Query, Build, Enrich     MMapGraphStore (.smpg)
MCP Tools (stdio)         Community Detection      FAISS mmap vectors (.smpv)
FastAPI                   Safety, Merkle           Async CRUD
```

### 5.2 Design Patterns Used
- **Factory Pattern** - `create_app()`
- **Abstract Interfaces** - `GraphStore`, `VectorStore`, `QueryEngine`
- **Dependency Injection** - Passed via constructors
- **Async/Await** - Throughout (FastAPI, MMapGraphStore, vector store)
- **Immutable Models** - msgspec.Struct with `frozen=True`
- **Handler Pattern** - JSON-RPC handlers with MethodHandler base

### 5.3 Data Model Partitioning
- **Structural** - Coordinates, signatures, complexity (AST-derived, immutable)
- **Semantic** - Docstrings, comments, tags, decorators (enriched, mutable)

---

## 6. Development Workflow

### Requirements
- Python 3.11+ (required for `X | Y` unions, `tomllib`, etc.)
- No external database: graph lives in `.smpg` files, vectors (optional, BYO) in `.smpv`
- Optional: Redis (`SMP_REDIS_URL`) for distributed rate limiting

### Setup
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### Linting & Type Checking
```bash
ruff check .                # Lint
ruff format .               # Format
mypy smp/                   # Type check
```

### Running Service
```bash
smp serve --port 8420                 # JSON-RPC over HTTP (POST /rpc)
smp ingest <dir>                      # Parse directory (structural only, no embeddings)
smp mcp                               # MCP server over stdio
smp backup --output backup.tar.gz     # Snapshot graph to gzipped tarball (+ manifest.json)
smp restore --input backup.tar.gz     # Restore graph from backup
smp compact                           # Rewrite journal, drop obsolete records
smp integrity                         # Full on-disk integrity check
```

### Pre-Commit Checklist
1. `ruff check .` - No lint errors
2. `ruff format .` - Code formatted
3. `mypy smp/` - No type errors
4. `pytest` - All tests pass

---

## 7. Summary: MCP Tool Exposure Readiness

**Current State:**
- ✅ 37 JSON-RPC handlers already implemented
- ✅ MCP server skeleton in `smp/protocol/mcp.py`
- ✅ All core logic accessible via handlers
- ✅ Comprehensive test coverage
- ✅ Type-annotated async/await throughout

**Ready-to-Expose Categories:**
1. **Query Tools** (7) - High-level codebase navigation
2. **Memory Tools** (3) - Update and ingest
3. **Enrichment Tools** (7) - Metadata generation
4. **Community Tools** (4) - Architectural analysis
5. **Safety Tools** (11) - Session & integrity management
6. **Sandbox Tools** (3) - Isolated execution
7. **Sync Tools** (4) - Merkle tree operations
8. **Telemetry Tools** (4) - Observability
9. **Handoff Tools** (2) - Coordination
10. **Advanced Query Tools** (4) - Impact analysis

**Total Exposable:** 49+ tools ready for MCP wrapper

---

## 8. Key Files to Understand

### Essential Starting Points
- `smp/core/models.py` - All data structures
- `smp/engine/interfaces.py` - Abstract contracts
- `smp/protocol/dispatcher.py` - JSON-RPC routing
- `smp/protocol/handlers/base.py` - Handler pattern
- `smp/cli.py` - Entry points (ingest, serve, etc.)

### Core Logic
- `smp/engine/query.py` - Query engine implementation
- `smp/engine/graph_builder.py` - Graph construction
- `smp/parser/base.py` - Parser framework
- `smp/store/interfaces.py` - Store contracts

### MCP Integration
- `smp/protocol/mcp.py` - MCP server implementation
- `smp/protocol/server.py` - FastAPI app factory

---

