# Structural Memory Protocol (SMP)

> **Give AI agents a programmer's brain — not text retrieval, but structural understanding.**

SMP is a codebase intelligence server that models source code as a live, multi-dimensional knowledge graph. While traditional RAG treats code as flat text — leading to context overflow, stale hallucinations, and broken architectural awareness — SMP builds a structural model that AI agents can navigate, reason over, and safely mutate, even in codebases exceeding 100,000 lines.

---

## Table of Contents

- [Why SMP](#why-smp)
- [Key Features](#key-features)
- [Architecture Overview](#architecture-overview)
- [How It Works](#how-it-works)
  - [1. Parser — AST Extraction](#1-parser--ast-extraction)
  - [2. Graph Builder — Structural Analysis](#2-graph-builder--structural-analysis)
  - [3. Linker — Namespaced Cross-File Resolution](#3-linker--namespaced-cross-file-resolution)
  - [4. Runtime Linker — eBPF Execution Traces](#4-runtime-linker--ebpf-execution-traces)
  - [5. Enricher — Static Metadata](#5-enricher--static-metadata)
  - [6. Community Detection — Architectural Clustering](#6-community-detection--architectural-clustering)
  - [7. SeedWalkEngine — Community-Routed Graph RAG](#7-seedwalkengine--community-routed-graph-rag)
  - [8. Agent Safety Layer](#8-agent-safety-layer)
  - [9. Sandbox Runtime](#9-sandbox-runtime)
- [Quickstart](#quickstart)
  - [Docker Compose](#docker-compose-fastest)
  - [Manual Installation](#manual-installation)
- [Protocol Reference](#protocol-reference)
  - [Memory Management](#memory-management)
  - [Structural Queries](#structural-queries)
  - [Context & Impact](#context--impact)
  - [Community Queries](#community-queries)
  - [Enrichment & Search](#enrichment--search)
  - [Agent Safety](#agent-safety)
  - [Sandbox](#sandbox)
  - [Swarm Handoff](#swarm-handoff)
- [Agent Integration](#agent-integration)
  - [Python SDK](#python-sdk)
  - [TypeScript SDK](#typescript-sdk)
  - [Full Agent Workflow](#full-agent-workflow)
- [MCP Integration](#mcp-integration)
- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [Contributing](#contributing)

---

## Why SMP

Standard RAG pipelines fail at code for three core reasons:

| Problem | What breaks | SMP's answer |
|---|---|---|
| **Context overflow** | 100k-line repos exceed any LLM window | Community-routed retrieval targets ~200 nodes, not the full graph |
| **No structural awareness** | Functions renamed, moved, or deleted invisibly | Live graph updated on every file change via watcher or git hook |
| **Hallucinated dependencies** | Flat-text models guess call chains | Namespaced static + eBPF runtime linker resolves exact edges |

SMP replaces guessing with a graph where every node is a real code entity (function, class, file, interface) and every edge is a verified relationship (CALLS, IMPORTS, INHERITS, TESTS). Agents query the structure, not the text.

---

## Key Features

**AI-First Architecture** — Purpose-built to prevent agents from breaking on large codebases. Every response includes a pre-computed structural summary so agents read metadata first and drill into raw data only when needed.

**MCP Native** — Fully supports the [Model Context Protocol](https://modelcontextprotocol.io/), making SMP a plug-in memory layer for any MCP-compatible AI IDE or agent framework.

**Community-Routed Graph RAG** — A hybrid pipeline: ChromaDB seeds discovery by vector similarity, then Neo4j performs structural N-hop traversal from those seeds. Retrieval is scoped to the relevant architectural cluster, not the entire codebase.

**Hybrid Linking** — Combines static AST analysis (Tree-sitter) with kernel-level runtime execution traces (eBPF) to resolve dynamic dependencies — dependency injection, metaprogramming, runtime dispatchers — that static analysis alone can never see.

**Two-Level Community Detection** — Louvain partitioning at coarse (architecture) and fine (routing) resolutions. Agents can query domain boundaries and coupling weights between modules.

**Blast Radius Analysis** — Quantify the exact set of nodes affected by a change before a single line is edited. Impact analysis runs on the graph in milliseconds.

**Merkle-Indexed Sync** — SHA-256 Merkle tree over all file nodes. Incremental sync is O(log n) — only diverging subtrees are re-indexed. Snapshots are cryptographically signed for secure distribution to new agent instances.

**Agent Safety Layer** — Sessions with MVCC conflict detection, guard checks, dry-run impact preview, checkpoints, audit log, and per-node locking. Agents cannot accidentally overwrite concurrent work.

**Sandbox Runtime** — Ephemeral microVM or Docker containers with Copy-on-Write filesystems, hard egress firewall, and eBPF trace capture. Safe execution for test runs, runtime edge resolution, and mutation testing.

**No LLM at Query Time** — Embeddings are generated once at index time. All retrieval, ranking, and response assembly are graph operations and arithmetic. No generative model is invoked during a query.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     CODEBASE (Files + Git)                      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Updates (Watch / Agent Push / commit_sha)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   MEMORY SERVER (SMP Core)                      │
│  ┌─────────────┐   ┌──────────────┐   ┌─────────────┐           │
│  │   PARSER    │──▶│ GRAPH BUILDER│──▶│  ENRICHER   │           │
│  │ (Tree-sitter│   │  + LINKER    │   │  (Static    │           │
│  │    AST)     │   │(Static+eBPF) │   │  Metadata)  │           │
│  └─────────────┘   └──────────────┘   └──────┬──────┘           │
│                                              │                  │
│  ┌───────────────────────────────────────────▼──────────────┐   │
│  │                    MEMORY STORE                          │   │
│  │  ┌──────────────────────────────────────────────┐        │   │
│  │  │  GRAPH DB (Neo4j)                            │        │   │
│  │  │  Structure · CALLS_STATIC · CALLS_RUNTIME    │        │   │
│  │  │  PageRank · Sessions · Audit · BM25 Index    │        │   │
│  │  └──────────────────────────────────────────────┘        │   │
│  │  ┌──────────────────────────────────────────────┐        │   │
│  │  │  VECTOR INDEX (ChromaDB)                     │        │   │
│  │  │  code_embedding per node (index-time only)   │        │   │
│  │  └──────────────────────────────────────────────┘        │   │
│  │  ┌──────────────────────────────────────────────┐        │   │
│  │  │  MERKLE INDEX                                │        │   │
│  │  │  SHA-256 per file · Package subtree hashes   │        │   │
│  │  │  Root hash = full codebase state             │        │   │
│  │  └──────────────────────────────────────────────┘        │   │
│  └──────────────────────────────┬───────────────────────────┘   │
└─────────────────────────────────┼───────────────────────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          ▼                       ▼                       ▼
┌─────────────────┐   ┌──────────────────────┐   ┌───────────────┐
│  QUERY ENGINE   │   │   SANDBOX RUNTIME    │   │  SWARM LAYER  │
│  Navigator      │   │  Ephemeral microVM / │   │  Peer Review  │
│  Reasoner       │   │  Docker + CoW fork   │   │  PR Handoff   │
│  SeedWalkEngine │   │  eBPF trace capture  │   └───────┬───────┘
│  Telemetry      │   │  Egress-firewalled   │           │
└────────┬────────┘   └──────────┬───────────┘           │
         └──────────────┬────────┘               ────────┘
                        │ SMP Protocol (Dispatcher)
                        ▼
        ┌─────────────────────────────────────────────┐
        │              AGENT LAYER                    │
        │   Agent A       Agent B       Agent C       │
        │   (Coder)       (Reviewer)    (Architect)   │
        └─────────────────────────────────────────────┘
```

---

## How It Works

### 1. Parser — AST Extraction

**Technology:** Tree-sitter (multi-language, fast, incremental)

Tree-sitter parses every source file into a typed Abstract Syntax Tree. The parser extracts functions, classes, variables, interfaces, imports, and exports — producing a structured document for the Graph Builder to consume.

**Extracted per file:**

```python
{
    "file_path": "src/auth/login.ts",
    "language": "typescript",
    "nodes": [
        {
            "id": "func_authenticate_user",
            "type": "function_declaration",
            "name": "authenticateUser",
            "start_line": 15,
            "end_line": 42,
            "signature": "authenticateUser(email: string, password: string): Promise<Token>",
            "docstring": "Validates user credentials and returns JWT...",
            "modifiers": ["async", "export"]
        },
        {
            "id": "class_AuthService",
            "type": "class_declaration",
            "name": "AuthService",
            "methods": ["login", "logout", "refresh"],
            "properties": ["tokenExpiry", "secretKey"]
        }
    ],
    "imports": [
        {"from": "./utils/crypto", "items": ["hashPassword", "compareHash"]},
        {"from": "../db/user",     "items": ["UserModel"]}
    ],
    "exports": ["authenticateUser", "AuthService"]
}
```

---

### 2. Graph Builder — Structural Analysis

The Graph Builder transforms AST output into a property graph stored in Neo4j. Every code entity becomes a node; every structural dependency becomes a typed, directed edge.

**Node types:**

| Node | Represents |
|---|---|
| `Repository` | Root node for the entire codebase |
| `Package` | Directory or module |
| `File` | Source file |
| `Class` | Class definition |
| `Function` | Function or method |
| `Variable` | Variable or constant |
| `Interface` | Type definition or interface |
| `Test` | Test file or test function |
| `Config` | Configuration file |
| `Community` | Louvain-detected structural cluster |

**Relationship types:**

| Relationship | Meaning |
|---|---|
| `CONTAINS` | Parent-child (Package → File) |
| `IMPORTS` | File imports File / Module |
| `DEFINES` | File defines Class / Function |
| `CALLS` | Function calls Function (namespaced) |
| `INHERITS` | Class inherits Class |
| `IMPLEMENTS` | Class implements Interface |
| `DEPENDS_ON` | General dependency |
| `TESTS` | Test covers Function / Class |
| `USES` | Function uses Variable / Type |
| `REFERENCES` | Variable references Variable |
| `MEMBER_OF` | Node belongs to Community |
| `BRIDGES` | Community connects to Community |

---

### 3. Linker — Namespaced Cross-File Resolution

The Linker runs after the Graph Builder and resolves every `CALLS` edge using each file's `imports` list as a namespace map. This prevents the classic ambiguity problem where the same function name exists in multiple files.

**Problem it solves:**

```
File A calls: save()
File B has:   save()   (src/db/user.ts)
File C has:   save()   (src/cache/session.ts)
```

Without namespacing, a linker guesses. SMP's Linker traces the import to the exact origin file first:

```
For each CALLS(caller → "save") edge:
  1. Look up caller's IMPORTS list
  2. Find the import entry that exposes "save"
     → e.g. import { save } from "../db/user"
  3. Resolve "../db/user" to absolute path → src/db/user.ts
  4. Find node with name="save" AND file="src/db/user.ts"
  5. Draw CALLS edge to that exact node

  If step 2 finds no import for "save":
  → Mark edge as CALLS_UNRESOLVED (reason="not in imports")
  → Flag for smp/linker/report
```

Every `CALLS` edge carries a `resolved` flag so agents always know whether a dependency is confirmed or ambiguous. Unresolved edges are reportable via `smp/linker/report`.

---

### 4. Runtime Linker — eBPF Execution Traces

Static linking resolves what the *source code says* will be called. The Runtime Linker resolves what *actually runs* — capturing real call chains from inside a sandbox via eBPF, then injecting `CALLS_RUNTIME` edges into the graph.

**What static linking cannot see:**

```typescript
// Dependency Injection — static linker sees no CALLS edge here
container.bind<IAuthService>("AuthService").to(JwtAuthService);

// Metaprogramming — target function name is a runtime variable
const method = config.get("handler");
this[method](payload);
```

**How runtime linking works:**

```
Agent spawns sandbox (smp/sandbox/spawn)
        │
        ▼
Agent runs test suite inside sandbox (smp/sandbox/execute, inject_ebpf: true)
        │
        ▼
eBPF daemon intercepts every function entry/exit at kernel level
        │
        ▼
SMP Runtime Linker processes trace → resolves targets → injects CALLS_RUNTIME edges
        │
        ▼
Graph DB now has a full hybrid call graph:
  CALLS_STATIC  = "source says this will be called"   (resolved at index time)
  CALLS_RUNTIME = "kernel confirmed this was called"   (resolved at execution time)
```

The result is a hybrid call graph that handles dependency injection, event buses, metaprogramming, plugin systems, and any other pattern that defeats static analysis.

---

### 5. Enricher — Static Metadata

The Enricher attaches human-readable metadata to structural nodes using only what already exists in the code: docstrings, inline comments, decorators, and type annotations. No LLM. No embeddings. Pure static extraction.

At index time, `code_embedding` is generated once per node from `signature + docstring` and stored in ChromaDB. This embedding is used exclusively for the seed phase of `smp/locate`. **No generative model is invoked at query time.**

**Enriched node schema (final):**

```json
{
    "id": "func_authenticate_user",
    "semantic": {
        "status": "enriched",
        "docstring": "Validates user credentials and returns a signed JWT.",
        "inline_comments": [
            {"line": 18, "text": "compare against bcrypt hash, not plaintext"}
        ],
        "decorators": ["@requires_db", "@rate_limited"],
        "annotations": {
            "params": {"email": "string", "password": "string"},
            "returns": "Promise<Token>",
            "throws": ["AuthenticationError", "DatabaseError"]
        },
        "tags": ["auth", "jwt", "session"],
        "source_hash": "a3f9c12d",
        "enriched_at": "2025-02-15T10:30:00Z"
    },
    "vector": {
        "code_embedding": [0.021, -0.134, 0.087, "..."],
        "embedding_input": "authenticateUser(email: string, password: string): Promise<Token> — Validates user credentials and returns a signed JWT.",
        "model": "text-embedding-3-small",
        "indexed_at": "2025-02-15T10:30:01Z"
    }
}
```

---

### 6. Community Detection — Architectural Clustering

**Purpose:** Automatically partition the codebase graph into structural clusters at two levels so agents can reason about domain boundaries and `smp/locate` can narrow its seed search to ~200 nodes instead of all 100k+.

**Two-level hierarchy:**

```
Level 0 — COARSE (global architecture view)
  e.g. "backend_core", "api_gateway", "data_layer"
  → Used by architecture agents to understand module ownership.
  → smp/community/boundaries shows coupling strength between modules.

Level 1 — FINE (search routing)
  e.g. "auth_core", "auth_oauth", "payments_stripe"
  → Subdivisions of coarse communities.
  → Used by smp/locate Phase 0 to scope seed search.
  → Every node carries both community_id_l0 and community_id_l1.
```

**Algorithm:** Louvain partitioning via Neo4j GDS at two resolutions (0.5 = coarse, 1.5 = fine), run over `CALLS_STATIC`, `CALLS_RUNTIME`, and `IMPORTS` edges. Labels are derived purely from topology — majority path prefix and top tags across member nodes. No LLM.

---

### 7. SeedWalkEngine — Community-Routed Graph RAG

`smp/locate` is SMP's primary feature discovery endpoint. It runs a four-phase pipeline:

```
Phase 0 — Community Routing
  Query vector compared to community centroid embeddings
  → Identify the 1-2 most relevant fine communities
  → Scope seed search to ~200 nodes in those communities

Phase 1 — Seed (ChromaDB)
  Run vector similarity search within scoped nodes
  → Return top-k seed nodes by cosine similarity

Phase 2 — Walk (Neo4j)
  Single Cypher query — no N+1 problem
  → N-hop traversal over CALLS_STATIC, CALLS_RUNTIME, IMPORTS, DEFINES
  → Captures structural neighbourhood of each seed

Phase 3 — Rank (Composite Score)
  final_score = α·vector_score + β·pagerank_norm + γ·heat_norm
  → PageRank reflects structural importance in the full graph
  → Heat score reflects how frequently the node has been accessed

Phase 4 — Structural Map
  Build adjacency list of edges between result nodes
  → Agents receive a renderable call chain, not just a flat list
```

---

### 8. Agent Safety Layer

SMP provides a full safety harness for agents operating in write mode:

**Sessions** — Every write operation must open a session declaring its scope and intent. Sessions are persisted in Neo4j with MVCC (multi-version concurrency control) for read sessions and exclusive locks for write sessions.

**Guard Checks** (`smp/guard/check`) — Pre-flight check before any write. Returns `blocked`, `warning`, or `clear` based on concurrent session conflicts, hot-node status (heat score > 90), lock status, and test coverage gaps.

**Dry Run** (`smp/dryrun`) — Proposes a change and receives a full impact preview: breaking vs. non-breaking verdict, list of affected callers, missing tests, and structural diff — before touching disk.

**Checkpoints** (`smp/checkpoint`) — Snapshot the current graph state for a set of files before writing. Enables rollback if a change produces unexpected results.

**Audit Log** — Every session, guard check, dry run, checkpoint, and write is recorded in Neo4j with timestamp and agent ID. Queryable via `smp/audit/log`.

---

### 9. Sandbox Runtime

Every sandbox is an ephemeral, isolated execution environment:

- **Docker or Firecracker microVM** — hard process isolation
- **Copy-on-Write filesystem** — changes never persist to the host
- **Hard egress firewall** — no network access by default; only whitelisted internal endpoints allowed
- **eBPF trace capture** — kernel-level call interception for runtime edge resolution
- **Testcontainers** — spin up local Postgres, Redis, or other services per sandbox run

Sandboxes are used for: running test suites to capture runtime edges, integrity verification (AST data-flow checks + mutation testing), and safe execution of agent-proposed code before committing.

---

## Quickstart

### Docker Compose (Fastest)

**Requirements:** Docker, Docker Compose

```bash
git clone https://github.com/your-org/smp.git
cd smp
cp .env.example .env        # Edit with your Neo4j password
docker compose up -d
curl http://localhost:8420/health
# → {"status":"ok"}
```

### Manual Installation

**Requirements:** Python 3.11, Neo4j 5.x

```bash
# 1. Clone and configure
git clone https://github.com/your-org/smp.git
cd smp
cp .env.example .env

# 2. Set up Python environment
python3.11 -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 3. Start the server
smp serve --port 8420

# 4. Ingest your project
smp ingest /path/to/your/project

# 5. Run a query
smp query "Where is the authentication logic handled?"
```

**Environment variables (`.env`):**

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
CHROMA_HOST=localhost
CHROMA_PORT=8000
SMP_PORT=8420
OPENAI_API_KEY=sk-...   # Used for code_embedding generation at index time only
```

---

## Protocol Reference

SMP uses **JSON-RPC 2.0** over stdio, HTTP, or WebSocket. Every method follows the same envelope:

```json
{
    "jsonrpc": "2.0",
    "method": "smp/<method>",
    "params": { ... },
    "id": 1
}
```

### Memory Management

#### `smp/update` — Sync a single file change

```json
{
    "jsonrpc": "2.0",
    "method": "smp/update",
    "params": {
        "file_path": "src/auth/login.ts",
        "content": "...",
        "change_type": "modified"   // "modified" | "created" | "deleted"
    },
    "id": 1
}
```

**Response:**
```json
{
    "result": {
        "status": "success",
        "nodes_added": 3,
        "nodes_updated": 12,
        "nodes_removed": 1,
        "relationships_updated": 8
    }
}
```

#### `smp/batch_update` — Sync multiple files atomically

```json
{
    "method": "smp/batch_update",
    "params": {
        "changes": [
            {"file_path": "src/auth/login.ts",      "content": "...", "change_type": "modified"},
            {"file_path": "src/auth/middleware.ts",  "content": "...", "change_type": "created"}
        ]
    }
}
```

#### `smp/sync` — Merkle-diff sync (O(log n))

Sends client root hash + per-file SHA-256 hashes. Server compares against its Merkle tree and returns exactly which files need to be pushed or pulled.

```json
{
    "method": "smp/sync",
    "params": {
        "client_root_hash": "e3b0c44298fc",
        "file_hashes": {
            "src/auth/login.ts":     "a3f9c12d",
            "src/utils/crypto.ts":   "c3a1f004"
        }
    }
}
```

#### `smp/index/export` — Export signed index snapshot

```json
{
    "method": "smp/index/export",
    "params": {
        "scope": "full",
        "signing_key_id": "key_prod_01"
    }
}
```

#### `smp/index/import` — Import and verify a signed snapshot

```json
{
    "method": "smp/index/import",
    "params": {
        "snapshot_id": "snap_4f8a2c",
        "source_url": "smp://snapshots/snap_4f8a2c.tar.zst",
        "expected_root_hash": "f7c2a19b3d84",
        "verify_signature": true
    }
}
```

---

### Structural Queries

#### `smp/navigate` — Find an entity and its relationships

```json
{
    "method": "smp/navigate",
    "params": {
        "query": "authenticateUser",
        "include_relationships": true
    }
}
```

#### `smp/trace` — Follow a relationship chain

```json
{
    "method": "smp/trace",
    "params": {
        "start": "func_authenticate_user",
        "relationship": "CALLS",
        "depth": 3,
        "direction": "outgoing"
    }
}
```

#### `smp/flow` — Trace data flow through the graph

```json
{
    "method": "smp/flow",
    "params": {
        "entry": "func_authenticate_user",
        "direction": "out",
        "depth": 4
    }
}
```

#### `smp/diff` — Structural diff between two commit SHAs

```json
{
    "method": "smp/diff",
    "params": {
        "from_sha": "abc1234",
        "to_sha": "def5678",
        "scope": "package:src/auth"
    }
}
```

#### `smp/why` — Explain why two nodes are connected

```json
{
    "method": "smp/why",
    "params": {
        "from": "func_authenticate_user",
        "to": "class_UserModel"
    }
}
```

---

### Context & Impact

#### `smp/context` — Get the programmer's mental model for a file

Returns a pre-computed structural summary (role, blast radius, risk level, test coverage, heat score) plus raw graph data: imports, importers, defined symbols, structurally similar files, entry points, and data flow.

```json
{
    "method": "smp/context",
    "params": {
        "file_path": "src/auth/login.ts",
        "scope": "edit"   // "edit" | "create" | "debug" | "review"
    }
}
```

**Summary fields in the response:**

| Field | Description |
|---|---|
| `role` | Topology-derived: `endpoint`, `service`, `core_utility`, `test`, `config`, `isolated`, `module` |
| `blast_radius` | Number of files that import this file |
| `api_layer_callers` | Callers originating from the API layer |
| `avg_complexity` | Average cyclomatic complexity of defined functions |
| `max_complexity` | Highest complexity function in the file |
| `has_tests` | Whether test coverage exists |
| `is_hot_node` | True if heat score > 90 |
| `heat_score` | Frequency of recent access (0–100) |
| `risk_level` | `high` / `medium` / `low` — derived from blast_radius and complexity |

#### `smp/impact` — Blast radius of a proposed change

```json
{
    "method": "smp/impact",
    "params": {
        "entity": "func_authenticate_user",
        "change_type": "signature_change"   // "signature_change" | "delete" | "move"
    }
}
```

#### `smp/locate` — Community-routed feature discovery

```json
{
    "method": "smp/locate",
    "params": {
        "query": "user registration flow",
        "seed_k": 3,
        "hops": 2,
        "top_k": 10
    }
}
```

Returns ranked results with `final_score`, `vector_score`, `pagerank`, `heat_score`, and a `structural_map` adjacency list of edges between result nodes.

---

### Community Queries

#### `smp/community/detect` — Run Louvain at two resolutions

```json
{
    "method": "smp/community/detect",
    "params": {
        "algorithm": "louvain",
        "relationship_types": ["CALLS_STATIC", "CALLS_RUNTIME", "IMPORTS"],
        "levels": [
            {"level": 0, "resolution": 0.5, "label": "coarse"},
            {"level": 1, "resolution": 1.5, "label": "fine"}
        ],
        "min_community_size": 5
    }
}
```

#### `smp/community/list` — List all communities

```json
{"method": "smp/community/list", "params": {"level": 1}}
```

#### `smp/community/get` — Get members and bridge edges of a community

```json
{
    "method": "smp/community/get",
    "params": {
        "community_id": "comm_auth_core",
        "node_types": ["Function", "Class"],
        "include_bridges": true
    }
}
```

#### `smp/community/boundaries` — Coupling strength between all community pairs

```json
{
    "method": "smp/community/boundaries",
    "params": {"level": 0, "min_coupling": 0.05}
}
```

Returns coupling weights and the specific bridge nodes responsible for cross-domain dependencies.

---

### Enrichment & Search

#### `smp/enrich` — Extract static metadata from a node

```json
{"method": "smp/enrich", "params": {"node_id": "func_authenticate_user", "force": false}}
```

Skips silently if `source_hash` is unchanged since last enrichment.

#### `smp/enrich/batch` — Enrich an entire scope

```json
{"method": "smp/enrich/batch", "params": {"scope": "package:src/auth", "force": false}}
```

#### `smp/enrich/stale` — List nodes whose source changed since last enrichment

```json
{"method": "smp/enrich/stale", "params": {"scope": "full"}}
```

#### `smp/enrich/status` — Enrichment coverage report

Returns `total_nodes`, `has_docstring`, `has_annotations`, `has_tags`, `no_metadata`, `stale`, and `coverage_pct`.

#### `smp/annotate` — Manually set metadata on a node

Used for `no_metadata` nodes that have nothing extractable from the AST.

```json
{
    "method": "smp/annotate",
    "params": {
        "node_id": "func_xT9_handler",
        "description": "Processes Stripe webhook payload and updates subscription status.",
        "tags": ["billing", "webhook", "stripe"]
    }
}
```

#### `smp/tag` — Bulk-tag nodes by scope

```json
{
    "method": "smp/tag",
    "params": {
        "scope": "package:src/payments",
        "tags": ["billing", "stripe", "pci-sensitive"],
        "action": "add"   // "add" | "remove" | "replace"
    }
}
```

#### `smp/search` — BM25 full-text search across enriched metadata

Backed by a Neo4j Full-Text Index (BM25). Scales to 100k+ nodes with no table scans.

```json
{
    "method": "smp/search",
    "params": {
        "query": "stripe webhook",
        "match": "all",
        "filter": {
            "node_types": ["Function", "Class"],
            "tags": ["billing"],
            "scope": "package:src/payments"
        },
        "top_k": 5
    }
}
```

---

### Agent Safety

#### `smp/session/open` — Open a write session

```json
{
    "method": "smp/session/open",
    "params": {
        "agent_id": "agent_coder_01",
        "task": "Refactor authentication middleware",
        "scope": ["src/auth/login.ts", "src/auth/middleware.ts"],
        "mode": "write"   // "read" | "write"
    }
}
```

#### `smp/guard/check` — Pre-flight safety check

```json
{
    "method": "smp/guard/check",
    "params": {
        "session_id": "sess_abc123",
        "target": "src/auth/login.ts"
    }
}
```

Returns `verdict`: `clear`, `warning`, or `blocked` along with reasons and recommended actions.

#### `smp/dryrun` — Preview impact of a proposed change

```json
{
    "method": "smp/dryrun",
    "params": {
        "session_id": "sess_abc123",
        "file_path": "src/auth/login.ts",
        "proposed_content": "..."
    }
}
```

Returns `verdict`: `safe` or `breaking`, with the list of affected nodes, missing tests, and a structural diff.

#### `smp/checkpoint` — Snapshot graph state before writing

```json
{
    "method": "smp/checkpoint",
    "params": {
        "session_id": "sess_abc123",
        "files": ["src/auth/login.ts"]
    }
}
```

#### `smp/session/close` — Close a session

```json
{
    "method": "smp/session/close",
    "params": {"session_id": "sess_abc123", "status": "completed"}
}
```

#### `smp/audit/log` — Query the audit log

```json
{
    "method": "smp/audit/log",
    "params": {
        "agent_id": "agent_coder_01",
        "since": "2025-02-15T00:00:00Z",
        "event_types": ["session_open", "dryrun", "write"]
    }
}
```

---

### Sandbox

#### `smp/sandbox/spawn` — Create an ephemeral sandbox

```json
{
    "method": "smp/sandbox/spawn",
    "params": {
        "runtime": "docker",   // "docker" | "firecracker"
        "image": "node:20-alpine",
        "workspace": "src/auth",
        "inject_ebpf": true
    }
}
```

#### `smp/sandbox/execute` — Run a command inside the sandbox

```json
{
    "method": "smp/sandbox/execute",
    "params": {
        "sandbox_id": "box_99x",
        "command": "npm test -- src/auth",
        "capture_traces": true
    }
}
```

#### `smp/sandbox/destroy` — Tear down a sandbox

```json
{"method": "smp/sandbox/destroy", "params": {"sandbox_id": "box_99x"}}
```

---

### Swarm Handoff

#### `smp/handoff/review` — Hand off a change to a peer-review agent

```json
{
    "method": "smp/handoff/review",
    "params": {
        "session_id": "sess_abc123",
        "reviewer_agent": "agent_reviewer_01",
        "notes": "Refactored token expiry handling."
    }
}
```

#### `smp/handoff/pr` — Generate a structured PR with structural diff

Returns a PR package containing: changed files, structural diff, new runtime edges discovered during sandbox execution, mutation test score, and guard check history.

---

## Agent Integration

### Python SDK

```python
import asyncio
from smp.client import SMPClient

async def main():
    async with SMPClient("http://localhost:8420") as client:

        # Feature discovery
        results = await client.locate("user registration flow")

        # Impact analysis
        impact = await client.assess_impact("src/auth/manager.py::authenticate")
        print(f"Change affects {impact['total_affected_nodes']} nodes")

        # Get editing context
        context = await client.get_context("src/auth/login.ts", scope="edit")
        print(f"Risk level: {context['summary']['risk_level']}")
        print(f"Blast radius: {context['summary']['blast_radius']} files")

asyncio.run(main())
```

### TypeScript SDK

```typescript
import { SMPClient } from "@smp/client";

const client = new SMPClient("http://localhost:8420");

// Locate a feature
const results = await client.locate("payment webhook handler");

// Assess impact before editing
const impact = await client.impact("func_process_payment", "signature_change");
console.log(`Affects ${impact.total_affected_nodes} nodes`);
```

### Full Agent Workflow

This is the recommended pattern for any agent performing a write operation:

```python
class CodingAgent:
    def __init__(self, smp_client):
        self.smp = smp_client

    def edit_file(self, file_path: str, instruction: str, new_code: str):
        # 1. Open a session — declare scope and intent upfront
        session = self.smp.call("smp/session/open", {
            "agent_id": self.agent_id,
            "task": instruction,
            "scope": [file_path],
            "mode": "write"
        })

        # 2. Pre-flight guard check — abort immediately if blocked
        guard = self.smp.call("smp/guard/check", {
            "session_id": session["session_id"],
            "target": file_path
        })
        if guard["verdict"] == "blocked":
            raise AbortError(guard["reasons"])

        # 3. Get full structural context — agents read summary first
        context = self.smp.call("smp/context", {
            "file_path": file_path,
            "scope": "edit"
        })

        # 4. Dry run — preview impact before touching disk
        dryrun = self.smp.call("smp/dryrun", {
            "session_id": session["session_id"],
            "file_path": file_path,
            "proposed_content": new_code,
        })
        if dryrun["verdict"] == "breaking":
            raise AbortError(dryrun["risks"])

        # 5. Checkpoint → write → sync memory
        self.smp.call("smp/checkpoint", {
            "session_id": session["session_id"],
            "files": [file_path]
        })
        write_to_disk(file_path, new_code)
        self.smp.call("smp/update", {
            "file_path": file_path,
            "content": new_code,
            "change_type": "modified"
        })

        # 6. Close session
        self.smp.call("smp/session/close", {
            "session_id": session["session_id"],
            "status": "completed"
        })
```

---

## MCP Integration

SMP is a native MCP server. Add it to your agent's MCP configuration to expose all SMP methods as tools:

```json
{
    "mcpServers": {
        "smp": {
            "url": "http://localhost:8420/mcp",
            "transport": "http"
        }
    }
}
```

Once connected, your MCP-compatible IDE or agent (Cursor, Claude Code, Windsurf, etc.) will have access to all `smp/*` methods as first-class tools, with full structural memory for every code change.

---

## Technology Stack

| Component | Technology | Rationale |
|---|---|---|
| **AST Parsing** | Tree-sitter | Multi-language, incremental, fast — no LLM |
| **Graph DB** | Neo4j 5.x | CALLS, IMPORTS, PageRank, BM25 full-text, community detection via GDS |
| **Vector Index** | ChromaDB | High-speed seed discovery at query time |
| **Merkle Index** | SHA-256 (in-process) | O(log n) incremental sync, secure snapshot distribution |
| **Community Detection** | Louvain (Neo4j GDS) | Topology-only, no LLM, reproducible |
| **Runtime Tracing** | eBPF (BCC / libbpf) | Kernel-level call capture — zero app instrumentation |
| **Sandbox Runtime** | Docker / Firecracker microVMs | Ephemeral, CoW filesystem, hard egress firewall |
| **Container Topology** | Testcontainers | Per-sandbox Postgres, Redis, etc. |
| **Mutation Testing** | Stryker (JS/TS) / mutmut (Python) | Deterministic, no LLM, anti-gamification |
| **Data Models** | msgspec | Zero-copy, schema-validated structs |
| **Protocol** | JSON-RPC 2.0 | Standard, simple, MCP-compatible |
| **Embeddings** | text-embedding-3-small (index time only) | Generated once per node; never at query time |
| **Language** | Python 3.11 (prototype) → Rust (production) | Start fast, optimize later |

---

## Project Structure

```
structural-memory/
├── server/
│   ├── core/
│   │   ├── parser.py            # AST extraction (Tree-sitter)
│   │   ├── graph_builder.py     # Build structural graph
│   │   ├── linker.py            # Static namespaced CALLS resolution
│   │   ├── linker_runtime.py    # eBPF trace ingestion → CALLS_RUNTIME edges
│   │   ├── enricher.py          # Static metadata extraction
│   │   ├── merkle.py            # Merkle tree builder + hash comparator
│   │   ├── index_distributor.py # Index export / import + signature verification
│   │   ├── community.py         # Louvain detection + MEMBER_OF writes
│   │   ├── telemetry.py         # Hot node tracking + heat scores
│   │   ├── store.py             # Graph DB interface + full-text index + PageRank
│   │   └── chroma_index.py      # ChromaDB collection management
│   ├── engine/
│   │   ├── navigator.py         # Graph traversal (navigate, trace, flow, why)
│   │   ├── reasoner.py          # Proactive context + summary computation
│   │   ├── seed_walk.py         # SeedWalkEngine: Seed & Walk pipeline
│   │   └── guard.py             # Guard checks, dry run, test-gap analysis
│   ├── sandbox/
│   │   ├── spawner.py           # Docker / Firecracker microVM lifecycle
│   │   ├── executor.py          # Command runner + stdout/stderr capture
│   │   ├── ebpf_collector.py    # eBPF daemon interface + trace → graph edges
│   │   ├── network_policy.py    # Egress firewall rules
│   │   └── verifier.py          # AST data-flow check + mutation test runner
│   ├── protocol/
│   │   ├── dispatcher.py        # @rpc_method decorator + method registry
│   │   └── handlers/
│   │       ├── memory.py        # smp/update, batch_update, sync, merkle/*
│   │       ├── index.py         # smp/index/export, import
│   │       ├── community.py     # smp/community/detect, list, get, boundaries
│   │       ├── query.py         # smp/navigate, trace, context, impact, locate, flow, diff, why
│   │       ├── enrichment.py    # smp/enrich, annotate, tag, search
│   │       ├── safety.py        # smp/session/*, guard/check, dryrun, checkpoint, lock, audit
│   │       ├── planning.py      # smp/plan, conflict
│   │       ├── sandbox.py       # smp/sandbox/spawn, execute, destroy
│   │       ├── verify.py        # smp/verify/integrity
│   │       ├── handoff.py       # smp/handoff/review, pr
│   │       └── telemetry.py     # smp/telemetry/*
│   └── main.py                  # Server entry point + full-text index init
├── clients/
│   ├── python_client.py         # Python SDK for agents
│   ├── typescript_client.ts     # TypeScript SDK for agents
│   └── cli.py                   # Manual interaction + debugging
├── watchers/
│   ├── file_watcher.py          # Watch for filesystem changes
│   └── git_hook.py              # Git-based incremental updates
└── tests/
    └── ...
```

**Protocol dispatcher pattern** — each method group lives in its own handler module with a `@rpc_method` decorator. No god-file `if/elif` chains.

```python
# protocol/dispatcher.py
def rpc_method(name: str):
    def decorator(fn):
        _registry[name] = fn
        return fn
    return decorator

def dispatch(method: str, params: dict, context: ServerContext):
    handler = _registry.get(method)
    if not handler:
        raise MethodNotFound(method)
    return handler(params, context)

# protocol/handlers/query.py
@rpc_method("smp/navigate")
def handle_navigate(params, ctx):
    return ctx.engine.navigator.navigate(
        params["query"], params.get("include_relationships", False)
    )

@rpc_method("smp/locate")
def handle_locate(params, ctx):
    return ctx.engine.seed_walk.locate(
        params["query"], params.get("seed_k", 3), params.get("hops", 2), params.get("top_k", 10)
    )
```

---

## Component Summary

| Component | Purpose |
|---|---|
| **Parser** | Extract AST from source (Tree-sitter) |
| **Graph Builder** | Create structural nodes and relationships |
| **Static Linker** | Namespace-aware cross-file CALLS resolution |
| **Runtime Linker** | eBPF execution traces → `CALLS_RUNTIME` edges |
| **Enricher** | Attach docstrings, annotations, tags, `code_embedding` |
| **Graph DB** | Neo4j — structure, PageRank, sessions, telemetry, BM25 |
| **Vector Index** | ChromaDB — `code_embedding` per node for seed phase |
| **Merkle Index** | SHA-256 tree — O(log n) incremental sync + secure distribution |
| **SeedWalkEngine** | `smp/locate` pipeline: vector seed → N-hop walk → composite rank |
| **Query Engine** | navigate, trace, context, impact, locate, flow, diff, why |
| **SMP Protocol** | JSON-RPC 2.0 via Dispatcher — handlers split by domain |
| **Agent Safety** | Sessions, guard checks, dry runs, checkpoints, audit log |
| **Telemetry** | Hot node tracking, heat scores, automatic safety escalation |
| **Community Detection** | Two-level Louvain — Graph RAG routing + architecture queries |
| **Sandbox Runtime** | Ephemeral microVM/Docker, CoW filesystem, egress firewall |
| **Integrity Gate** | AST data-flow check + deterministic mutation testing |
| **Swarm Handoff** | Peer review pass-off + structured PR with structural diff |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions, coding standards, and how to add new protocol methods or language parsers.

---

## Documentation

- [Architecture Guide](ARCHITECTURE.md) — Deep dive into the Graph RAG pipeline and storage layer.
- [API Reference](API.md) — Full JSON-RPC 2.0 method specification with all parameters and response schemas.
- [User Guide](USER_GUIDE.md) — Tutorials and advanced agent workflows.
- [Contributing](CONTRIBUTING.md) — How to extend SMP with new parsers, methods, and integrations.

---

*SMP — giving AI agents the structural memory to master any codebase.*