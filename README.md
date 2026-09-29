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
  - [4. Call Resolution — Ingest + Placeholder Linking](#4-call-resolution--ingest--placeholder-linking)
  - [5. Enricher — Static Metadata](#5-enricher--static-metadata)
  - [6. Community Detection — Architectural Clustering](#6-community-detection--architectural-clustering)
  - [7. Locate — Keyword Search + Structural Expansion](#7-locate--keyword-search--structural-expansion)
  - [8. Agent Safety Layer](#8-agent-safety-layer)
  - [9. Sandbox Runtime](#9-sandbox-runtime)
- [Quickstart](#quickstart)
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
- [Comparison: SMP vs codebase-memory-mcp](#comparison-smp-vs-codebase-memory-mcp)
- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [Contributing](#contributing)

---

## Why SMP

Standard RAG pipelines fail at code for three core reasons:

| Problem | What breaks | SMP's answer |
|---|---|---|
| **Context overflow** | 100k-line repos exceed any LLM window | Keyword search returns top-k, not the full graph |
| **No structural awareness** | Functions renamed, moved, or deleted invisibly | Live graph updated on every file change via watcher or git hook |
| **Hallucinated dependencies** | Flat-text models guess call chains | Same-file + global placeholder linking |

SMP replaces guessing with a graph where every node is a real code entity (function, class, file, interface)
and every edge is a structural relationship (CALLS, IMPORTS, INHERITS, TESTS). Agents query the structure,
not the text.

---

## Key Features

**AI-First Architecture** — Purpose-built to prevent agents from breaking on large codebases. Every response includes a pre-computed structural summary so agents read metadata first and drill into raw data only when needed.

**MCP Native** — Fully supports the [Model Context Protocol](https://modelcontextprotocol.io/), making SMP a plug-in memory layer for any MCP-compatible AI IDE or agent framework.

**Keyword Search + Structural Traversal** — `smp/search` and `smp/locate` score keywords against names, docstrings,
descriptions, tags, IDs, and file paths, then expand over the call/import graph. No vector seeding, no BM25.

**Call Linking** — Same-file calls are resolved at ingest; remaining cross-file calls are linked by global
name matching (`resolve_placeholders`). This over-approximates across files and languages — safe for impact
analysis, though same-named functions may link together.

**Community Detection** — Connected-component clustering over the call/import graph. Agents can query module
boundaries and coupling weights between communities.

**Blast Radius Analysis** — Quantify the exact set of nodes affected by a change before a single line is edited. Impact analysis runs on the graph in milliseconds.

**Merkle-Indexed Sync** — SHA-256 Merkle tree over all file nodes. Incremental sync is O(log n) — only diverging subtrees are re-indexed. Snapshots are cryptographically signed for secure distribution to new agent instances.

**Agent Safety Layer** — Sessions with MVCC conflict detection, guard checks, dry-run impact preview, checkpoints, audit log, and per-node locking. Agents cannot accidentally overwrite concurrent work.

**Sandbox Runtime** — Process-level isolation: commands run as child processes inside a private working directory
with an optional command allowlist (`SMP_SANDBOX_ALLOWED_COMMANDS`). No containers, no eBPF trace capture.

**Bring-Your-Own Embeddings** — Ingest does NOT create embeddings and SMP ships no embedding model. Vectors live
in the FAISS-backed mmap vector store (`.smpv`) and are written only via the `smp/vector/upsert` API; keyword
search works without any vectors.

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
│  │    AST)     │   │(Static)       │   │  Metadata)  │           │
│  └─────────────┘   └──────────────┘   └──────┬──────┘           │
│                                              │                  │
│  ┌───────────────────────────────────────────▼──────────────┐   │
│  │                    MEMORY STORE                          │   │
│  │  ┌──────────────────────────────────────────────┐        │   │
│  │  │  GRAPH STORE (MMapGraphStore, .smpg)         │        │   │
│  │  │  Structure · CALLS · Sessions · Audit        │        │   │
│  │  │  Keyword index (names/docs/tags/paths)       │        │   │
│  │  └──────────────────────────────────────────────┘        │   │
│  │  ┌──────────────────────────────────────────────┐        │   │
│  │  │  VECTOR STORE (FAISS mmap, .smpv)            │        │   │
│  │  │  BYO embeddings via smp/vector/* API only    │        │   │
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
│  Navigator      │   │  Child processes in  │   │  Peer Review  │
│  Reasoner       │   │  private work dirs   │   │  PR Handoff   │
│  Keyword locate │   │  Command allowlist   │   └───────┬───────┘
│  Telemetry      │   │  Process isolation   │           │
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

**Supported languages (14):** Python; JavaScript (`.js/.jsx/.mjs/.cjs`); TypeScript (`.ts/.mts/.cts`) and TSX;
Java; C; C++; C#; Go; Rust; PHP; Ruby; Swift; Kotlin; MATLAB (see `_LANGUAGE_SPECS` in
`smp/store/graph/parser.py` and `DEFAULT_EXTENSIONS` in `smp/cli.py`).

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

The Graph Builder transforms AST output into a property graph stored in the memory-mapped journal graph store
(`.smpg` files, `smp/store/graph/`). The store is self-contained — no external database. Every code entity
becomes a node; every structural dependency becomes a typed, directed edge.

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
| `Community` | Connected-component cluster |

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

### 3. Linker — Same-File Resolution + Global Placeholder Linking

The Linker runs at ingest and again afterwards. Calls whose target is defined in the same file are resolved
immediately; every other call is recorded as an edge to a `::name::` placeholder. `resolve_placeholders` then
links each placeholder to every node with a matching structural name — across files AND languages.

This deliberately over-approximates: the safe direction for impact analysis, since no caller is missed. The
trade-off is that same-named functions may link together:

```
File A calls: save()
File B has:   save()   (src/db/user.py)
File C has:   save()   (src/cache/session.py)
→ placeholder ::save:: links to BOTH definitions
```

Placeholders are kept so later ingests can link newly added files, and edge dedup keeps re-runs idempotent.

---

### 4. Call Resolution — No Runtime Tracing

SMP's call graph is static only. There is no runtime linker: no eBPF collector, no kernel-level execution
tracing, and no sandbox trace ingestion. Dynamic dispatch (dependency injection, event buses, metaprogramming)
is visible only where a same-named definition exists statically — `resolve_placeholders` will link it, along
with any other same-named definitions.

---

### 5. Enricher — Static Metadata

The Enricher attaches human-readable metadata to structural nodes using only what already exists in the code:
docstrings, inline comments, decorators, and type annotations. No LLM. Pure static extraction.

Ingest does NOT create embeddings and SMP ships no embedding model. The FAISS-backed mmap vector store (`.smpv`,
`smp/vector/`) accepts bring-your-own embeddings via the `smp/vector/upsert` API only. Keyword search
(`smp/search`, `smp/locate`) works without any vectors.

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
    }
}
```

---

### 6. Community Detection — Connected Components

**Purpose:** Automatically partition the codebase graph into structural clusters so agents can reason about domain
boundaries and coupling between modules.

**Method:** Connected-component analysis over the undirected projection of the graph, optionally filtered by
relationship types (`smp/community/detect`). Results are cached server-side so `smp/community/list`,
`smp/community/get`, and `smp/community/boundaries` return consistent IDs. No Louvain, no PageRank, no LLM.

---

### 7. Locate — BM25 Search + Structural Expansion

`smp/locate` is SMP's primary feature discovery endpoint. It ranks every node with true Okapi BM25
(`smp/engine/bm25.py`: `K1=1.2`, `B=0.75`, length normalisation) over field-weighted tokens —
`name` 5.0, `tags` 3.0, `id` 2.0, `docstring` 2.0, `description`/`decorators` 1.5, `file_path`/`signature` 1.0 —
with camelCase/snake_case tokenisation and an exact-name boost. Every match reports `matched_on` provenance
plus `score`, `signature`, and `start_line`/`end_line`:

```
smp/search:  "graph store mmap" → MMapGraphStore 62.09 (name, id, file_path), total 1279
smp/locate:  "upsert node"      → upsert_node 69.24, total 111
```

`smp/search` adds `match` (`any`/`all`, actually enforced), `node_types` / `tags` / `scope` filters, and
`top_k`/`offset` pagination with `total` / `has_more` / `next_offset` metadata. `smp/search_code` adds
`compact` / `full` (bounded snippets) / `files` modes; `smp/file_outline`, `smp/dead_code`, and
`smp/index_coverage` round out discovery. No vector seeding, no PageRank — vectors remain strictly
bring-your-own via `smp/vector/*`.

---

### 8. Agent Safety Layer

SMP provides a full safety harness for agents operating in write mode:

**Sessions** — Every write operation must open a session declaring its scope and intent. Sessions and locks are
persisted in the graph store, with exclusive locks for write sessions.

**Guard Checks** (`smp/guard/check`) — Pre-flight check before any write. Returns `blocked`, `warning`, or `clear` based on concurrent session conflicts, hot-node status (heat score > 90), lock status, and test coverage gaps.

**Dry Run** (`smp/dryrun`) — Proposes a change and receives a full impact preview: breaking vs. non-breaking verdict, list of affected callers, missing tests, and structural diff — before touching disk.

**Checkpoints** (`smp/checkpoint`) — Snapshot the current graph state for a set of files before writing. Enables rollback if a change produces unexpected results.

**Audit Log** — Every session, guard check, dry run, checkpoint, and write is recorded with timestamp and agent
ID. Queryable via `smp/audit/log`.

---

### 9. Sandbox Runtime

Every sandbox is an isolated execution environment:

- **Child processes in a private working directory** — process-level isolation, not containers
- **Command allowlist** — restrict runnable commands via `SMP_SANDBOX_ALLOWED_COMMANDS`
- **Timeouts and stdin capture** — bounded execution with stdout/stderr capture

Sandboxes are used for safe execution of agent-proposed code before committing.

---

## Quickstart

### Manual Installation

**Requirements:** Python 3.11+ (see `requires-python = ">=3.11"` in `pyproject.toml`). No external database — the
graph lives in a self-contained `.smpg` file and vectors (optional, bring-your-own) in `.smpv`.

```bash
# 1. Clone and configure
git clone https://github.com/your-org/smp.git
cd smp
cp .env.example .env

# 2. Set up Python environment
python3.11 -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 3. Start the server (writes to .smp/graph.smpg by default)
smp serve --port 8420 --graph-path .smp/graph.smpg

# 4. Ingest your project (structural parsing only — creates NO embeddings)
smp ingest /path/to/your/project --graph-path .smp/graph.smpg

# 5. Run a query
curl -X POST http://localhost:8420/rpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "smp/locate", "params": {"query": "authentication logic"}}'
```

**Environment variables (`.env`):**

```env
SMP_GRAPH_PATH=.smp/graph.smpg
SMP_VECTOR_PATH=.smp/smp.smpv
SMP_HOST=0.0.0.0
SMP_PORT=8420
# Optional Redis for distributed rate limiting
SMP_REDIS_URL=
```

---

## Protocol Reference

SMP uses **JSON-RPC 2.0** over HTTP (`smp serve`, `POST /rpc`). AI agents can also connect via MCP over stdio
(`smp mcp`). Every method follows the same envelope:

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

#### `smp/locate` — Keyword feature discovery

```json
{
    "method": "smp/locate",
    "params": {
        "query": "user registration flow",
        "fields": ["name", "docstring", "tags"],
        "top_k": 10
    }
}
```

Returns ranked matches with `entity`, `file`, `matched_on`, `docstring`, and `tags`. Scoring is plain keyword
matching (name hits outrank docstring hits; tag hits add on) — no vectors, no PageRank.

---

### Community Queries

#### `smp/community/detect` — Find connected-component communities

```json
{
    "method": "smp/community/detect",
    "params": {
        "relationship_types": ["CALLS", "IMPORTS"],
        "resolutions": []
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

#### `smp/search` — Keyword search across names, docs, tags, IDs, and file paths

Scored keyword matching over the graph store (name/id/path/docstring/description weights). No BM25 index.

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

#### `smp/sandbox/spawn` — Create an isolated sandbox (child process in a private working directory)

```json
{
    "method": "smp/sandbox/spawn",
    "params": {
        "name": "auth-tests",
        "template": null,
        "files": {}
    }
}
```

#### `smp/sandbox/execute` — Run a command inside the sandbox

```json
{
    "method": "smp/sandbox/execute",
    "params": {
        "sandbox_id": "box_99x",
        "command": ["npm", "test", "--", "src/auth"],
        "timeout": 120
    }
}
```

#### `smp/sandbox/kill` — Tear down a sandbox

```json
{"method": "smp/sandbox/kill", "params": {"execution_id": "box_99x"}}
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

Returns a PR package containing: changed files, structural diff, and guard check history.

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

SMP is a native MCP server over stdio. Add it to your agent's MCP configuration to expose SMP methods as tools:

```json
{
    "mcpServers": {
        "smp": {
            "command": "smp",
            "args": ["mcp", "--graph-path", ".smp/graph.smpg"]
        }
    }
}
```

Once connected, your MCP-compatible IDE or agent (Cursor, Claude Code, Windsurf, etc.) will have access to all `smp/*` methods as first-class tools, with full structural memory for every code change.

---

## Comparison: SMP vs codebase-memory-mcp

Independent agent-judged benchmark, both systems run live against this repo (SMP itself: SMP 3769 nodes /
21944 edges vs codebase-memory 5722 nodes / 26251 edges — the gap is markdown `Section` nodes, which SMP's
parser does not extract). Final score: **SMP 79 — codebase-memory 64**.

| Dimension (0–10) | SMP | codebase-memory-mcp |
|---|---|---|
| Search precision | **9** — correct class first (`MMapGraphStore 62.09` + `matched_on`), true BM25 | 5 — BM25 top-5 all test files, real class rank 7 |
| Recall / scale | 7 | **9** — 16 labels / 21 edge types |
| Trace | **9** — callers + snippets, `fan_in`/`risk`/`evidence` | 4 — file-level only, errors on ambiguous names |
| Architecture | **9** — repo-relative packages, 14 languages, clean URL routes, coupling boundaries | 5 — noisy routes (`/path/a`), basename-fragment packages |
| Pagination / provenance | **9** — `total`/`has_more`/`next_offset` everywhere | 7 |
| Outline / snippets | 8 | 8 |
| Coverage honesty | 9 — explicit best-effort caveat | 8 — generation hash |
| Ad-hoc graph queries | 0 — no Cypher (path-expression engine exists, not yet exposed) | **10** — Cypher `query_graph` + git-diff `detect_changes` |
| Sessions / sandbox | **10** — open→lock (fencing)→sandbox→destroy round-trips live; exclusive | 0 — read-only by design |
| Freshness | 9 — local `.smpg` you own | 8 — hosted index |

**Verdict:** SMP wins for agent work (search, trace, architecture, and everything stateful). codebase-memory-mcp
keeps two genuine credits: Cypher ad-hoc queries and git-diff impact mapping — plus raw index scale. Git
diffing itself needs no graph tool (`git diff`, `gh`, editor views cover it); SMP's `smp/diff` + `smp/dryrun`
cover the agent loop those can't: graph-aware blast radius before anything is written.

**Credits:** SMP — true Okapi BM25, `matched_on` transparency, repo-relative architecture, only stateful
primitives. codebase-memory-mcp — massive fresh index, deep `get_code_snippet` (66 members + 239 callers),
Cypher, honest generation-hashed coverage.

---

## Technology Stack

| Component | Technology | Rationale |
|---|---|---|
| **AST Parsing** | Tree-sitter (14 languages, see §1) | Functions, classes, interfaces, calls — no LLM |
| **Graph Store** | `MMapGraphStore` (`.smpg` journal) | Self-contained; no external DB |
| **Vector Store** | FAISS-backed mmap (`.smpv`) | Bring-your-own embeddings via `smp/vector/*`; ingest creates none |
| **Merkle Index** | SHA-256 (in-process) | O(log n) incremental sync, secure snapshot distribution |
| **Community Detection** | Connected components (in-process) | Topology-only, no LLM, reproducible |
| **Sandbox Runtime** | Child processes in private work dirs | Bounded execution with command allowlist |
| **Backups** | Gzipped tarballs (snapshot + `manifest.json`) | Via `smp backup` / `smp restore` |
| **Data Models** | msgspec | Zero-copy, schema-validated structs |
| **Protocol** | JSON-RPC 2.0 over HTTP + MCP over stdio | Standard, simple, agent-compatible |
| **Embeddings** | None built in (BYO only) | No embedding model ships with SMP; ingest creates no vectors |
| **Language** | Python 3.11+ (`requires-python = ">=3.11"`) | Modern typing (`X \| Y`), `tomllib`, tree-sitter |

---

## Project Structure

```
smp/
├── cli.py                   # CLI: ingest | serve | mcp | backup | restore | compact | integrity
├── logging.py               # Structured logging
├── core/
│   ├── models.py            # GraphNode, GraphEdge, NodeType, EdgeType, method params (msgspec)
│   └── config.py            # Settings from env (SMP_GRAPH_PATH, SMP_VECTOR_PATH, SMP_HOST/PORT)
├── engine/
│   ├── query.py             # Keyword locate/search, navigate, trace, context, impact, flow
│   └── graph_builder.py     # Graph ingestion and edge resolution
├── store/
│   ├── interfaces.py        # Abstract store interfaces
│   └── graph/               # Memory-mapped journal graph store (.smpg)
│       ├── mmap_store.py    # MMapGraphStore + resolve_placeholders
│       ├── parser.py        # Tree-sitter structural parsing (14 languages)
│       ├── query.py         # Graph queries
│       └── journal.py       # Append-only journal
├── vector/                  # FAISS-backed mmap vector store (.smpv, BYO embeddings only)
│   ├── mmap_vector.py
│   └── faiss_index.py
├── protocol/
│   ├── server.py            # FastAPI app: JSON-RPC over HTTP (~50 smp/* methods)
│   ├── mcp.py               # MCP server over stdio
│   └── handlers/            # query, memory, enrichment, community, session, vector, sandbox, ...
├── runtime/
│   └── sandbox.py           # Child-process sandbox runtime
├── observability/
│   └── backup.py            # backup/restore/compact (gzipped tarball + manifest.json)
└── ...
```

**Handler pattern** — each method group lives in its own handler module with plain async functions.

```python
# protocol/handlers/query.py
async def search(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    p = msgspec.convert(params, SearchParams)
    engine = ctx["engine"]
    return await engine.search(p.query, p.match, p.filter, p.top_k)

# protocol/handlers/community.py
async def community_detect(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    return await detect(params.get("relationship_types"), ctx)
```

---

## Component Summary

| Component | Purpose |
|---|---|
| **Parser** | Extract AST from source (Tree-sitter, 14 languages) |
| **Graph Builder** | Create structural nodes and relationships |
| **Linker** | Same-file call resolution at ingest + global name-based placeholder linking |
| **Enricher** | Attach docstrings, annotations, tags (static only; no embeddings) |
| **Graph Store** | `MMapGraphStore` — memory-mapped journal (`.smpg`), keyword index, sessions, telemetry |
| **Vector Store** | FAISS-backed mmap (`.smpv`) — bring-your-own embeddings via `smp/vector/*` |
| **Merkle Index** | SHA-256 tree — O(log n) incremental sync + secure distribution |
| **Query Engine** | navigate, trace, context, impact, locate, search, flow, diff, why |
| **SMP Protocol** | JSON-RPC 2.0 over HTTP (`smp serve`) + MCP over stdio (`smp mcp`) |
| **Agent Safety** | Sessions, guard checks, dry runs, checkpoints, audit log |
| **Telemetry** | Hot node tracking, heat scores, automatic safety escalation |
| **Community Detection** | Connected components over the call/import graph + boundary queries |
| **Sandbox Runtime** | Child processes in private work dirs, command allowlist |
| **Integrity Gate** | Full on-disk integrity check (`smp integrity`) |
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