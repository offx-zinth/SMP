# SMP Project Structure Exploration Summary

## Overview
**SMP (Structural Memory Protocol)** is a graph-based codebase intelligence system that provides AI agents with a programmer's brain instead of flat-text retrieval. It's built on Python 3.11+, FastAPI, Neo4j, ChromaDB, and tree-sitter.

- **Total Python Code:** ~9,111 lines
- **Stack:** Python 3.11+, FastAPI, msgspec, tree-sitter, Neo4j, ChromaDB, pytest
- **Protocol:** JSON-RPC 2.0 over FastAPI + MCP (Model Context Protocol)

---

## 1. Main Source Code Organization (`/smp` directory)

### Directory Structure
```
smp/
├── core/               # Data models and core structures
│   ├── models.py       # GraphNode, GraphEdge, NodeType, EdgeType, SemanticProperties, StructuralProperties
│   ├── background.py   # Background task management
│   └── merkle.py       # Merkle tree indexing
├── engine/             # Core processing logic
│   ├── query.py        # Query engine (navigate, trace, context, impact, locate, search, flow)
│   ├── graph_builder.py # Graph ingestion and edge resolution
│   ├── enricher.py     # Static semantic enrichment
│   ├── community.py    # Community detection (Louvain algorithm)
│   ├── embedding.py    # Embedding service
│   ├── linker.py       # Cross-file dependency resolution
│   ├── runtime_linker.py # eBPF runtime linking
│   ├── seed_walk.py    # Community-routed graph RAG
│   ├── safety.py       # Agent safety layer
│   ├── sandbox.py      # Sandbox utilities
│   ├── handoff.py      # Handoff/coordination
│   ├── integrity.py    # Integrity verification
│   ├── notification.py # Event notifications
│   ├── telemetry.py    # Telemetry & observability
│   ├── pagerank.py     # PageRank scoring
│   └── interfaces.py   # Abstract base classes
├── parser/             # Source code parsing
│   ├── base.py         # TreeSitterParser abstract base
│   ├── python_parser.py # Python parser implementation
│   ├── typescript_parser.py # TypeScript/JavaScript parser
│   └── registry.py     # Parser registry (factory pattern)
├── protocol/           # API layer
│   ├── server.py       # FastAPI application factory
│   ├── mcp.py          # MCP server implementation
│   ├── dispatcher.py   # JSON-RPC dispatcher
│   ├── router.py       # HTTP routing
│   └── handlers/       # JSON-RPC method handlers (see below)
├── sandbox/            # Code execution in isolated environments
│   ├── executor.py     # Command execution
│   ├── spawner.py      # Container/VM spawning
│   ├── docker_sandbox.py # Docker sandbox
│   └── ebpf_collector.py # eBPF trace collection
├── store/              # Persistence layer
│   ├── interfaces.py   # Abstract store interfaces
│   ├── chroma_store.py # ChromaDB vector store
│   └── graph/          # Neo4j graph store implementations
├── agent.py            # High-level agent API
├── client.py           # JSON-RPC client
├── cli.py              # Command-line interface
├── __init__.py         # Package init
└── logging.py          # Structured logging
```

---

## 2. Core Functionality and Tools

### 2.1 Parser Layer (`smp/parser/`)
**Purpose:** Extract code structure into typed nodes and edges using tree-sitter AST analysis

**Key Classes:**
- `TreeSitterParser` (abstract) - Base parser with error recovery
- `PythonParser` - Extracts functions, classes, imports, decorators, type hints
- `TypeScriptParser` - Extracts TypeScript/JavaScript entities
- `ParserRegistry` - Dispatcher for language selection

**Supported Languages:**
- Python (.py)
- TypeScript (.ts, .tsx)
- JavaScript (.js, .jsx)

**Output:** `Document` with nodes, edges, and parse errors

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

#### Advanced Features
- **Community Detection** - Louvain algorithm at two resolutions
- **Seed Walk Engine** - Vector + graph hybrid RAG
- **Runtime Linker** - eBPF traces for dynamic dependencies
- **Safety Layer** - MVCC sessions, locks, dry-run simulation
- **Merkle Indexing** - O(log n) incremental sync

---

### 2.3 Store Layer (`smp/store/`)

#### GraphStore Interface
Abstract base with implementations for Neo4j:

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

#### VectorStore Interface
ChromaDB implementation:
- `upsert_embedding()` - Store vector + metadata
- `search()` - Similarity search
- `delete_by_file()` - Cleanup

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
smp/search        → SearchHandler        - Semantic search
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
  - `neo4j_store` - Session-scoped graph store
  - `clean_graph` - Per-test fresh graph with cleanup
  - `make_node()` - Factory for test nodes
  - `make_edge()` - Factory for test edges
  - `vector_store` - Vector store fixture
  - `make_document()` - Factory for parsed documents

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
JSON-RPC 2.0              Query, Build, Enrich     Neo4j, ChromaDB
MCP Tools                 Community Detection       Abstract Interfaces
FastAPI                   Safety, Merkle            Async CRUD
```

### 5.2 Design Patterns Used
- **Factory Pattern** - `ParserRegistry`, `create_app()`, `create_embedding_service()`
- **Abstract Interfaces** - `GraphStore`, `VectorStore`, `Parser`, `GraphBuilder`, `SemanticEnricher`, `QueryEngine`
- **Dependency Injection** - Passed via constructors
- **Async/Await** - Throughout (FastAPI, Neo4j, ChromaDB)
- **Immutable Models** - msgspec.Struct with `frozen=True`
- **Handler Pattern** - JSON-RPC handlers with MethodHandler base

### 5.3 Data Model Partitioning
- **Structural** - Coordinates, signatures, complexity (AST-derived, immutable)
- **Semantic** - Docstrings, comments, tags, decorators (enriched, mutable)

---

## 6. Development Workflow

### Requirements
- Python 3.11+ (required for `X | Y` unions, `tomllib`, etc.)
- Neo4j database
- ChromaDB vector store

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
python3.11 -m smp.cli serve              # FastAPI server
python3.11 -m smp.cli ingest <dir>       # Parse directory
python3.11 -m smp.protocol.mcp           # MCP server (stdio)
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

