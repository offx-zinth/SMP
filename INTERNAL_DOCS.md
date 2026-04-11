# SMP Internal Technical Documentation

This document provides a deep-dive into the internal architecture, design patterns, and data flows of the Structural Memory Protocol (SMP). It is intended for contributors and engineers maintaining the system.

---

## 🏗 Core Architecture

SMP is designed as a **Layered Architecture** to ensure strict separation of concerns between the communication interface, business logic, and persistence layers.

### 1. Layered Breakdown
*   **Protocol Layer (`smp.protocol`)**: The "Entry Point." Implements a JSON-RPC 2.0 interface over FastAPI. It handles request validation, routing (dispatching), and response serialization.
*   **Engine Layer (`smp.engine`)**: The "Brain." Contains the core logic for graph construction, semantic enrichment, and complex querying. It is agnostic of the transport layer.
*   **Store Layer (`smp.store`)**: The "Memory." Provides an abstraction over Neo4j (Graph) and ChromaDB (Vector). It uses interface-based design to decouple the engine from specific database implementations.
*   **Parser Layer (`smp.parser`)**: The "Senses." Uses Tree-sitter to translate raw source code into a structural representation (AST) that the engine can process.
*   **Core Layer (`smp.core`)**: The "Skeleton." Defines the shared data models using `msgspec.Struct` for high-performance serialization and type safety.

### 2. Design Patterns Used
*   **Registry Pattern (`ParserRegistry`)**: Maps language identifiers to their respective parser implementations. This allows for O(1) lookup and lazy instantiation of language-specific parsers.
*   **Interface/Abstract Base Class (ABC)**: Used in `interfaces.py` across the store and engine layers. This ensures that the `QueryEngine` can work with any `VectorStore` or `GraphStore` implementation.
*   **Facade Pattern (`SMPClient`)**: Simplifies the interaction with the JSON-RPC server by providing a high-level, async Python API that hides the underlying HTTP and JSON-RPC boilerplate.
*   **Dependency Injection**: Protocol handlers are injected with a context object containing the `engine`, `store`, and `registry`, making the system highly testable and configurable.

---

## 📦 Module Documentation

### `smp.core`
**Responsibility**: Domain models and protocol schemas.
*   `models.py`: Defines `GraphNode`, `GraphEdge`, and the `Params` structs for every RPC method.
*   `background.py`: Implements `BackgroundRunner` for managing decoupled processes.

### `smp.engine`
**Responsibility**: High-level logic orchestration.
*   `graph_builder.py`: Translates `Document` objects from the parser into graph mutations.
*   `query.py`: Implements the `DefaultQueryEngine` which merges results from vector and graph stores.
*   `enricher.py`: Performs semantic analysis (docstring extraction, type resolution) and interacts with LLMs.
*   `safety.py`: Manages `LockManager` and `SessionManager` to prevent concurrent modification conflicts.

### `smp.protocol`
**Responsibility**: API Gateway and Request Routing.
*   `server.py`: The FastAPI app factory.
*   `dispatcher.py`: Routes JSON-RPC methods to their corresponding handlers.
*   `handlers/`: Modular logic for specific API endpoints (e.g., `query.py`, `memory.py`).

### `smp.store`
**Responsibility**: Physical data persistence.
*   `graph/neo4j_store.py`: Implementation of Cypher queries for graph operations.
*   `vector/chroma_store.py`: Implementation of vector embeddings and similarity search.

### `smp.parser`
**Responsibility**: Code-to-Graph translation.
*   `base.py`: Base `TreeSitterParser` class.
*   `python_parser.py` / `typescript_parser.py`: Language-specific AST traversal logic.

---

## 🔌 API Catalog

### Python SDK (`smp.client.SMPClient`)

| Method | Params | Return | Edge Cases / Errors |
| :--- | :--- | :--- | :--- |
| `navigate` | `entity_id: str` | `dict` | Returns empty if ID is not found in Neo4j. |
| `trace` | `start_id: str`, `edge_type: str`, `depth: int` | `list[dict]` | Can lead to exponential result size if `depth` is too high. |
| `get_context` | `file_path: str`, `scope: str` | `dict` | Fails if file was deleted since last ingestion. |
| `assess_impact` | `entity_id: str`, `change_type: str` | `dict` | Complexity scales with the connectivity of the node. |
| `locate` | `query: str`, `top_k: int` | `list[dict]` | Returns low-confidence results if the vector space is sparse. |
| `update` | `file_path: str`, `content: str` | `dict` | Large files may hit `DEFAULT_MAX_FILE_SIZE` limit. |

### JSON-RPC Endpoints (`smp/protocol/handlers/`)

| Endpoint | Handler | Primary Logic | Potential Failures |
| :--- | :--- | :--- | :--- |
| `smp/navigate` | `QueryHandler` | `QueryEngine.navigate()` | Node not found error. |
| `smp/update` | `MemoryHandler` | `Parser` $\rightarrow$ `Enricher` $\rightarrow$ `Builder` | Parser syntax error in source code. |
| `smp/enrich` | `EnrichmentHandler` | `SemanticEnricher.enrich()` | LLM API timeout or rate limit. |
| `smp/sandbox/spawn` | `SandboxHandler` | `SandboxSpawner.spawn()` | Resource exhaustion on the host. |

---

## 🔄 Data Flow Analysis

### 1. Ingestion Flow (The "Write" Path)
`Local File` $\rightarrow$ `CLI/Client` $\rightarrow$ `ParserRegistry` $\rightarrow$ `TreeSitterParser` $\rightarrow$ `Document (AST)` $\rightarrow$ `SemanticEnricher` $\rightarrow$ `GraphBuilder` $\rightarrow$ `Neo4jGraphStore` $\rightarrow$ `Neo4j DB`.

**Key Transformation**: Raw text is converted into a `Document` containing `GraphNode` and `GraphEdge` objects, which are then persisted as nodes and relationships in Neo4j.

### 2. Query Flow (The "Read" Path)
`Client` $\rightarrow$ `JSON-RPC Server` $\rightarrow$ `Dispatcher` $\rightarrow$ `QueryHandler` $\rightarrow$ `QueryEngine` $\rightarrow$ `(VectorStore $\cup$ GraphStore)` $\rightarrow$ `Merged Result` $\rightarrow$ `Client`.

**Key Transformation**: A semantic query is first converted to a vector embedding to find candidate nodes in ChromaDB, which are then hydrated with structural relationships from Neo4j.

### 3. Enrichment Flow (The "Optimization" Path)
`GraphNode` $\rightarrow$ `SemanticEnricher` $\rightarrow$ `Source Code Extraction` $\rightarrow$ `Static Analysis` $\rightarrow$ `Semantic Metadata` $\rightarrow$ `Neo4j Update`.

**Key Transformation**: Nodes are enhanced with high-level semantic meaning (e.g., "This function handles JWT validation") based on docstrings and implementation details.
