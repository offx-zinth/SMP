# Architecture Guide: Structural Memory Protocol (SMP)

The Structural Memory Protocol (SMP) is designed to provide AI agents with a "programmer's mental model" of a codebase. Unlike traditional RAG, which treats code as a series of text chunks, SMP treats code as a structured graph of interrelated entities.

## 🎯 Design Goals
- **Precision over Probability:** Replace "likely" text matches with "exact" structural relationships.
- **Architectural Awareness:** Enable agents to understand domain boundaries and module coupling.
- **Scalability:** Support massive codebases by routing queries to specific structural communities.
- **Hybrid Truth:** Combine the "what the code says" (static) with "what the code does" (runtime).

---

## ⚙️ The Ingestion Pipeline

The ingestion pipeline transforms raw source code into a queryable knowledge graph.

### 1. Parser (AST Extraction)
SMP uses **Tree-sitter** to perform fast, incremental parsing of multiple languages. It extracts high-level entities:
- **Nodes:** Classes, Functions, Variables, Interfaces.
- **Metadata:** Signatures, docstrings, modifiers (e.g., `async`, `export`).
- **Dependencies:** Import statements and export lists.

### 2. Graph Builder & The Linker
The Graph Builder creates the initial nodes and relationships. The **Linker** then resolves these relationships to ensure accuracy.

#### Static Linking (Namespaced Resolution)
To avoid ambiguity (e.g., two different files having a `save()` function), the Static Linker uses the file's `imports` as a namespace map. It traces a call to its exact origin file, marking edges as `resolved: true` or `CALLS_UNRESOLVED`.

#### Runtime Linking (eBPF Traces)
Static analysis cannot resolve Dependency Injection or Metaprogramming. SMP uses a **Runtime Linker** that:
1. Spawns a sandboxed environment.
2. Executes the code (e.g., via a test suite).
3. Captures kernel-level function entries/exits using **eBPF**.
4. Injects `CALLS_RUNTIME` edges into the graph.

### 3. Enricher
The Enricher attaches human-readable semantic metadata to structural nodes without using an LLM. It extracts:
- Docstrings and inline comments.
- Decorators and type annotations.
- Source hashes (to detect when a node becomes "stale" and needs re-enrichment).

### 4. Community Detection
SMP uses the **Louvain Algorithm** via Neo4j GDS to partition the graph into two levels of structural clusters:
- **Level 0 (Coarse):** High-level architectural domains (e.g., `api_gateway`, `data_layer`).
- **Level 1 (Fine):** Detailed functional modules (e.g., `auth_oauth`, `payments_stripe`).

Each community is assigned a **centroid embedding** (the mean of its members' embeddings), enabling efficient query routing.

---

## 🔍 The Query Engine: SeedWalkEngine

The `SeedWalkEngine` implements a 4-phase pipeline to find the most relevant code for a given query.

### Phase 0: Route
The query embedding is compared against the **Level-1 Community Centroids** in ChromaDB. If the confidence exceeds a threshold, the search is scoped to that specific community (~200 nodes), drastically reducing noise.

### Phase 1: Seed
A vector search is performed in ChromaDB to find the top-K "seed" nodes whose signatures or docstrings most closely match the query.

### Phase 2: Walk
From the seeds, the engine performs a multi-hop traversal in Neo4j, following `CALLS_STATIC`, `CALLS_RUNTIME`, and `IMPORTS` edges. This captures the structural context (who calls this? what does this call?).

### Phase 3: Rank
Nodes are ranked using a composite score:
$$\text{Score} = \alpha \cdot \text{VectorSimilarity} + \beta \cdot \text{NormalizedPageRank} + \gamma \cdot \text{HeatScore}$$
- **Vector Similarity:** Relevance to the query.
- **PageRank:** Structural importance in the graph.
- **Heat Score:** Frequency of execution (from telemetry/runtime traces).

### Phase 4: Assemble
The engine produces a ranked list of `RankedResult` objects and a `structural_map` (adjacency list) allowing the agent to visualize the call chain.

---

## 💾 Persistence Layer

SMP utilizes a dual-store strategy to balance speed and structure.

| Store | Technology | Role | Data Held |
| :--- | :--- | :--- | :--- |
| **Graph Store** | **Neo4j** | Structural Truth | Entities, Relationships, Communities, PageRank, Full-Text Index. |
| **Vector Store** | **ChromaDB** | Entry Point | Node Embeddings, Community Centroids. |

---

## 🔌 MCP Integration

SMP implements the **Model Context Protocol (MCP)**. This allows it to serve as a "Codebase Memory Server" for any MCP-compatible client. Instead of the agent reading files blindly, it calls SMP tools to:
1. `locate`: Find the right starting point in a massive repo.
2. `get_context`: Get a structural summary of a file and its dependencies.
3. `assess_impact`: Find all nodes affected by a potential change.
