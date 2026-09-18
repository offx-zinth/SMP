# The Structural Memory Protocol (SMP)

A framework for giving AI agents a "programmer's brain" — not text retrieval, but structural understanding.

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
│  │ (AST/Tree-  │   │ + LINKER     │   │ (Static     │           │
│  │  sitter)    │   │ (Static +    │   │  Metadata)  │           │
│  │             │   │  eBPF Runtime│   │             │           │
│  └─────────────┘   └──────────────┘   └──────┬──────┘           │
│                                              │                  │
│  ┌───────────────────────────────────────────▼──────────────┐   │
│  │                    MEMORY STORE                          │   │
│  │                                                          │   │
│  │  ┌─────────────────────────────────────┐                 │   │
│  │  │  GRAPH STORE (mmap `.smpg`)         │                 │   │
│  │  │  Structure · CALLS · placeholders   │                 │   │
│  │  │  Sessions · Audit · Telemetry       │                 │   │
│  │  │  Keyword index (in-process)         │                 │   │
│  │  └─────────────────────────────────────┘                 │   │
│  │                                                          │   │
│  │  ┌─────────────────────────────────────┐                 │   │
│  │  │  VECTOR STORE (FAISS `.smpv`)       │                 │   │
│  │  │  Caller-supplied embeddings only    │                 │   │
│  │  │  (ingest creates none; BYO via     │                 │   │
│  │  │   smp/vector/upsert)                │                 │   │
│  │  └─────────────────────────────────────┘                 │   │
│  │                                                          │   │
│  │  ┌─────────────────────────────────────┐                 │   │
│  │  │  MERKLE INDEX                       │                 │   │
│  │  │  SHA-256 leaf per file node         │                 │   │
│  │  │  Package subtree hashes             │                 │   │
│  │  │  Root hash = full codebase state    │                 │   │
│  │  └─────────────────────────────────────┘                 │   │
│  └──────────────────────────────┬───────────────────────────┘   │
└─────────────────────────────────┼───────────────────────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          │                       │                       │
          ▼                       ▼                       ▼
┌─────────────────┐   ┌──────────────────────┐   ┌───────────────┐
│  QUERY ENGINE   │   │   SANDBOX RUNTIME    │   │  SWARM LAYER  │
│  Navigator      │   │  Ephemeral microVM/  │   │  Peer Review  │
│  Reasoner       │   │  Docker + CoW fork   │   │  PR Handoff   │
│  Query Engine │   │  eBPF trace capture  │   │               │
│  Telemetry      │   │  Egress-firewalled   │   └───────┬───────┘
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

## Part 1: The Memory Server

### A. Parser (AST Extraction)

**Technology:** Tree-sitter (multi-language, fast, incremental)

**Input:** File path + content

**Output:** Abstract Syntax Tree with typed nodes

```python
# What gets extracted per file
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
        {"from": "../db/user", "items": ["UserModel"]}
    ],
    "exports": ["authenticateUser", "AuthService"]
}
```

---

### B. Graph Builder (Structural Analysis)

**Graph Schema:**

```
┌─────────────────────────────────────────────────────────────┐
│                      NODE TYPES                             │
├─────────────────────────────────────────────────────────────┤
│  Repository    │ Root node                                  │
│  Package       │ Directory/module                           │
│  File          │ Source file                                │
│  Class         │ Class definition                           │
│  Function      │ Function/method                            │
│  Variable      │ Variable/constant                          │
│  Interface     │ Type definition/interface                  │
│  Test          │ Test file/function                         │
│  Config        │ Configuration file                         │
│  Community     │ Connected-component structural cluster       │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    RELATIONSHIP TYPES                       │
├─────────────────────────────────────────────────────────────┤
│  CONTAINS      │ Parent-child (Package → File)              │
│  IMPORTS       │ File imports File/Module                   │
│  DEFINES       │ File defines Class/Function                │
│  CALLS         │ Function calls Function (namespaced)       │
│  INHERITS      │ Class inherits Class                       │
│  IMPLEMENTS    │ Class implements Interface                 │
│  DEPENDS_ON    │ General dependency                         │
│  TESTS         │ Test tests Function/Class                  │
│  USES          │ Function uses Variable/Type                │
│  REFERENCES    │ Variable references Variable               │
│  MEMBER_OF     │ Node belongs to Community                  │
│  BRIDGES       │ Community connects to Community            │
└─────────────────────────────────────────────────────────────┘
```

**Example Graph Node:**

```json
{
    "id": "func_authenticate_user",
    "type": "Function",
    "name": "authenticateUser",
    "file": "src/auth/login.ts",
    "community_id": "comm_auth_core",
    "signature": "authenticateUser(email: string, password: string): Promise<Token>",
    "metrics": {
        "complexity": 4,
        "lines": 28,
        "parameters": 2
    },
    "relationships": {
        "CALLS": ["func_hashPassword", "func_compareHash", "func_generateToken"],
        "DEPENDS_ON": ["class_UserModel"],
        "DEFINED_IN": "file_auth_login_ts",
        "MEMBER_OF": "comm_auth_core"
    }
}
```

---

### B1. The Linker (Namespaced Cross-File Resolution)

The Linker runs after the Graph Builder and resolves every `CALLS` edge using the file's `imports` list as a namespace map. This prevents ambiguous links when the same function name exists across multiple files.

**The Problem:**

```
File A calls: save()
File B has: save()   (src/db/user.ts)
File C has: save()   (src/cache/session.ts)
```

Without namespacing, the linker guesses. With it, it traces the import to the exact origin file first.

**Resolution Algorithm:**

```
For each CALLS(caller → "save") edge:
  1. Look up caller's IMPORTS list
  2. Find the import entry that exposes "save"
     → e.g. import { save } from "../db/user"
  3. Resolve "../db/user" to absolute path → src/db/user.ts
  4. Find node with name="save" AND file="src/db/user.ts"
  5. Draw CALLS edge to that exact node

  If step 2 finds no import for "save":
  → Mark edge as CALLS_UNRESOLVED (name="save", reason="not in imports")
  → Flag for smp/linker/report
```

**Linker State in the Graph DB:**

Every `CALLS` edge carries a `resolved` flag so agents always know if a dependency is confirmed or ambiguous.

```json
{
    "edge": "CALLS",
    "from": "func_authenticate_user",
    "to": "func_hashPassword",
    "resolved": true,
    "import_source": "src/utils/crypto.ts"
}
```

```json
{
    "edge": "CALLS_UNRESOLVED",
    "from": "func_process_data",
    "to_name": "save",
    "resolved": false,
    "reason": "ambiguous — save exists in 3 files, none imported directly"
}
```

**Protocol:**

```json
// smp/linker/report — list all unresolved edges in the graph
{
    "jsonrpc": "2.0",
    "method": "smp/linker/report",
    "params": {
        "scope": "full"   // "full" | "package:<path>" | "file:<path>"
    },
    "id": 24
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "unresolved_count": 4,
        "unresolved": [
            {
                "caller": "func_process_data",
                "file": "src/pipeline/runner.ts",
                "to_name": "save",
                "candidates": [
                    "src/db/user.ts:save",
                    "src/cache/session.ts:save",
                    "src/storage/blob.ts:save"
                ],
                "action": "add_import",
                "action_target": "src/pipeline/runner.ts"
            }
        ]
    },
    "id": 24
}
```

---

### B2. The Runtime Linker (eBPF Execution Traces)

Static linking resolves what the *source says* will be called. The Runtime Linker resolves what *actually runs* — capturing real call chains from inside a sandbox via eBPF, then injecting `CALLS_RUNTIME` edges into the graph.

**Why static linking alone isn't enough:**

```
// Dependency Injection — static linker sees no CALLS edge here at all
container.bind<IAuthService>("AuthService").to(JwtAuthService);

// Metaprogramming — target function name is a runtime variable
const method = config.get("handler");
this[method](payload);
```

The static linker marks these as `CALLS_UNRESOLVED`. The runtime linker resolves them by actually executing the code path inside a sandboxed environment and capturing the kernel-level syscall trace via eBPF.

**How it works:**

```
Agent spawns sandbox (smp/sandbox/spawn)
        │
        ▼
Agent runs test suite inside sandbox (smp/sandbox/execute, inject_ebpf: true)
        │
        ▼
eBPF daemon intercepts: every function entry/exit at kernel level
        │
        ▼
SMP Runtime Linker processes trace → resolves targets → injects CALLS_RUNTIME edges
        │
        ▼
Graph DB now has full hybrid call graph:
  CALLS_STATIC  = "source says this will be called"    (resolved at index time)
  CALLS_RUNTIME = "kernel confirmed this was called"   (resolved at execution time)
```

**CALLS_RUNTIME edge schema:**

```json
{
    "edge": "CALLS_RUNTIME",
    "from": "func_process_payment",
    "to":   "func_handle_stripe_webhook",
    "resolved_via": "ebpf_trace",
    "sandbox_id":   "box_99x",
    "commit_sha":   "a1b2c3d4",
    "call_count":   3,
    "first_seen":   "2025-02-15T10:44:09Z"
}
```

**Protocol — query runtime edges specifically:**

```json
// smp/linker/runtime — get all CALLS_RUNTIME edges for a node
{
    "jsonrpc": "2.0",
    "method": "smp/linker/runtime",
    "params": {
        "node_id": "func_process_payment",
        "commit_sha": "a1b2c3d4"
    },
    "id": 25
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "node_id": "func_process_payment",
        "runtime_callees": [
            {
                "node_id":      "func_handle_stripe_webhook",
                "file":         "src/payments/webhook.ts",
                "call_count":   3,
                "was_static_unresolved": true
            }
        ],
        "static_only_callees": ["func_validate_amount"],
        "unresolved_remaining": 0
    },
    "id": 25
}
```

**Purpose:** Attach human-readable metadata to structural nodes using only what already exists in the code — docstrings, comments, annotations, and decorators. No LLM. No embeddings. Pure static extraction.

---

#### smp/enrich — Extract static metadata from a node

Reads docstrings, inline comments, decorators, and type annotations directly off the AST. Skips silently if `source_hash` is unchanged since last enrichment.

```json
// Request
{
    "jsonrpc": "2.0",
    "method": "smp/enrich",
    "params": {
        "node_id": "func_authenticate_user",
        "force": false   // true = re-enrich even if source_hash unchanged
    },
    "id": 10
}

// Response — enriched
{
    "jsonrpc": "2.0",
    "result": {
        "node_id": "func_authenticate_user",
        "status": "enriched",   // "enriched" | "skipped" | "no_metadata"
        "docstring": "Validates user credentials and returns a signed JWT for the session.",
        "inline_comments": [
            {"line": 18, "text": "compare against bcrypt hash, not plaintext"},
            {"line": 31, "text": "token expiry pulled from env config"}
        ],
        "decorators": ["@requires_db", "@rate_limited"],
        "annotations": {
            "params": {"email": "string", "password": "string"},
            "returns": "Promise<Token>",
            "throws": ["AuthenticationError", "DatabaseError"]
        },
        "tags": [],
        "source_hash": "a3f9c12d",
        "enriched_at": "2025-02-15T10:30:00Z"
    },
    "id": 10
}

// Response — already fresh, nothing to do
{
    "jsonrpc": "2.0",
    "result": {
        "node_id": "func_authenticate_user",
        "status": "skipped",
        "reason": "source_hash unchanged"
    },
    "id": 10
}

// Response — node has no extractable metadata
{
    "jsonrpc": "2.0",
    "result": {
        "node_id": "func_xT9_handler",
        "status": "no_metadata",
        "reason": "no docstring, decorators, or type annotations found"
    },
    "id": 10
}

// Error — node not found
{
    "jsonrpc": "2.0",
    "error": {
        "code": -32001,
        "message": "Node not found",
        "data": {"node_id": "func_authenticate_user"}
    },
    "id": 10
}
```

---

#### smp/enrich/batch — Enrich a scope at once

```json
// Request
{
    "jsonrpc": "2.0",
    "method": "smp/enrich/batch",
    "params": {
        "scope": "package:src/auth",   // "full" | "package:<path>" | "file:<path>"
        "force": false
    },
    "id": 11
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "enriched": 24,
        "skipped": 6,        // source_hash unchanged
        "no_metadata": 3,    // nothing extractable — see node_ids for smp/annotate targets
        "failed": 0,
        "no_metadata_nodes": [
            "func_xT9_handler",
            "func_a1_proc",
            "class_TmpHelper"
        ]
    },
    "id": 11
}
```

---

#### smp/enrich/stale — List nodes whose source changed since last enrichment

Useful before a batch re-enrich — shows exactly what's out of date without running the full enrichment pass.

```json
// Request
{
    "jsonrpc": "2.0",
    "method": "smp/enrich/stale",
    "params": {
        "scope": "full"   // "full" | "package:<path>" | "file:<path>"
    },
    "id": 12
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "stale_count": 4,
        "stale_nodes": [
            {
                "node_id": "func_authenticate_user",
                "file": "src/auth/login.ts",
                "last_enriched": "2025-02-10T08:00:00Z",
                "current_hash": "b7d2e91f",
                "enriched_hash": "a3f9c12d"
            },
            {
                "node_id": "class_AuthService",
                "file": "src/auth/login.ts",
                "last_enriched": "2025-02-10T08:00:00Z",
                "current_hash": "c3a1f004",
                "enriched_hash": "99de12ab"
            }
        ]
    },
    "id": 12
}
```

---

#### smp/annotate — Manually set metadata on a node

For `no_metadata` nodes that have nothing extractable. Stored and queried identically to auto-enriched fields.

```json
// Request
{
    "jsonrpc": "2.0",
    "method": "smp/annotate",
    "params": {
        "node_id": "func_xT9_handler",
        "description": "Processes Stripe webhook payload and updates subscription status in DB.",
        "tags": ["billing", "webhook", "stripe"]
    },
    "id": 13
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "node_id": "func_xT9_handler",
        "status": "annotated",
        "manually_set": true,
        "annotated_at": "2025-02-15T11:00:00Z"
    },
    "id": 13
}

// Error — annotation would overwrite a docstring without force flag
{
    "jsonrpc": "2.0",
    "error": {
        "code": -32002,
        "message": "Node already has extracted docstring. Set force: true to override.",
        "data": {"node_id": "func_xT9_handler"}
    },
    "id": 13
}
```

---

#### smp/annotate/bulk — Annotate multiple nodes in one call

```json
// Request
{
    "jsonrpc": "2.0",
    "method": "smp/annotate/bulk",
    "params": {
        "annotations": [
            {
                "node_id": "func_xT9_handler",
                "description": "Processes Stripe webhook, updates subscription status.",
                "tags": ["billing", "webhook"]
            },
            {
                "node_id": "func_a1_proc",
                "description": "Runs nightly aggregation job for analytics pipeline.",
                "tags": ["analytics", "cron"]
            }
        ]
    },
    "id": 14
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "annotated": 2,
        "failed": 0
    },
    "id": 14
}
```

---

#### smp/tag — Bulk-tag nodes by scope

```json
// Request — add tags
{
    "jsonrpc": "2.0",
    "method": "smp/tag",
    "params": {
        "scope": "package:src/payments",
        "tags": ["billing", "stripe", "pci-sensitive"],
        "action": "add"   // "add" | "remove" | "replace"
    },
    "id": 15
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "nodes_affected": 31,
        "action": "add",
        "scope": "package:src/payments"
    },
    "id": 15
}

// Request — remove a tag that was applied by mistake
{
    "jsonrpc": "2.0",
    "method": "smp/tag",
    "params": {
        "scope": "package:src/payments",
        "tags": ["pci-sensitive"],
        "action": "remove"
    },
    "id": 16
}
```

---

#### smp/search — Keyword search across names, docstrings, descriptions, tags, IDs, and file paths

Scored term matching, computed in-process against the mmap graph store — no external index, no BM25 library.
Each query term contributes per-field weights (name and node ID highest, then docstring, then description and file
path); `match: "all"` requires every term to score, `match: "any"` requires at least one.

```json
// Request
{
    "jsonrpc": "2.0",
    "method": "smp/search",
    "params": {
        "query": "stripe webhook",
        "match": "all",            // "all" = AND, "any" = OR across query terms
        "filter": {
            "node_types": ["Function", "Class"],
            "tags": ["billing"],
            "scope": "package:src/payments"
        },
        "top_k": 5
    },
    "id": 17
}

// Response — results ranked by keyword score
{
    "jsonrpc": "2.0",
    "result": {
        "matches": [
            {
                "id": "a1b2c3d4::Function::handle_stripe_webhook::120",
                "type": "Function",
                "name": "handle_stripe_webhook",
                "file_path": "src/payments/webhook.py",
                "score": 9
            },
            {
                "id": "e5f6a7b8::Class::StripeClient::10",
                "type": "Class",
                "name": "StripeClient",
                "file_path": "src/payments/stripe.py",
                "score": 5
            }
        ],
        "total": 2
    },
    "id": 17
}

// Response — no matches
{
    "jsonrpc": "2.0",
    "result": {
        "matches": [],
        "total": 0,
        "hint": "Try broadening scope or using match: any"
    },
    "id": 17
}
```

---

#### smp/enrich/status — Enrichment coverage report

```json
// Request
{
    "jsonrpc": "2.0",
    "method": "smp/enrich/status",
    "params": {
        "scope": "full"
    },
    "id": 18
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "total_nodes": 1240,
        "has_docstring": 834,
        "has_annotations": 910,
        "has_tags": 412,
        "manually_annotated": 17,
        "no_metadata": 89,
        "stale": 4,
        "coverage_pct": 92.8
    },
    "id": 18
}
```

---

**Enriched Node (final schema):**

```json
{
    "id": "func_authenticate_user",
    "structural": { "...": "..." },
    "semantic": {
        "status": "enriched",
        "docstring": "Validates user credentials and returns a signed JWT for the session.",
        "description": null,
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
        "manually_set": false,
        "source_hash": "a3f9c12d",
        "enriched_at": "2025-02-15T10:30:00Z"
    }
}
```

> **Vector policy:** SMP ships no embedding model and ingest creates no embeddings. The FAISS-backed vector store
> (`.smpv`) holds only caller-supplied embeddings written via `smp/vector/upsert` and queried via
> `smp/vector/search`. Keyword search (`smp/search`, `smp/locate`) never touches vectors.

---

### D. Community Detection

**Purpose:** Automatically partition the codebase graph into structural clusters at **two levels** — coarse
(architecture overview) and fine (module view) — so agents can reason about domain boundaries and narrow queries.

**Two-level hierarchy:**

```
Level 0 — COARSE (global architecture view)
  e.g. "backend_core", "api_gateway", "data_layer"
  → Used by architecture agents to understand module ownership.
  → smp/community/boundaries shows coupling strength between these.

Level 1 — FINE (module view)
  e.g. "auth_core", "auth_oauth", "payments_stripe", "payments_refunds"
  → Subdivisions of coarse communities.
  → Every node carries both community_id_l0 and community_id_l1.
```

**How it works — purely topological, no LLM, no embeddings:**

```
1. Traverse the selected relationship types from each unvisited node (iterative DFS),
   collecting connected components in-process — no external graph database.

2. For each community at each level, derive a label from topology:
   → majority_path_prefix: most common src/ subdirectory among members
   → top_tags: most frequent semantic tags across enriched members

3. Write community_id_l0 + community_id_l1 onto every node as properties.
   Create Community nodes at both levels, link fine → coarse via CHILD_OF.
   Detect cross-community edges → write BRIDGES with coupling_weight.
```

**Community Node schema:**

```json
{
    "id": "comm_auth_core",
    "type": "Community",
    "level": 1,
    "parent_community": "comm_backend_core",
    "label": "auth",
    "majority_path_prefix": "src/auth",
    "top_tags": ["auth", "jwt", "session", "credentials"],
    "member_count": 47,
    "file_count": 6,
    "internal_edge_count": 183,
    "external_edge_count": 12,
    "detected_at": "2025-02-15T10:00:00Z"
}
```

**Protocol:**

```json
// smp/community/detect — Partition the graph into connected components over the selected
// relationship types. Triggered on demand and when smp/sync detects structural changes.
{
    "jsonrpc": "2.0",
    "method": "smp/community/detect",
    "params": {
        "relationship_types": ["CALLS", "IMPORTS"],
        "resolutions": [
            {"level": 0, "label": "coarse"},
            {"level": 1, "label": "fine"}
        ],
        "min_community_size": 5
    },
    "id": 19
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "level": 1,
        "communities": [
            {"community_id": "comm_0", "size": 410, "level": 1},
            {"community_id": "comm_1", "size": 320, "level": 1},
            {"community_id": "comm_2", "size": 280, "level": 1}
        ],
        "total": 14,
        "node_count": 1240
    },
    "id": 19
}
```

```json
// smp/community/list — List all communities at a given level
{
    "jsonrpc": "2.0",
    "method": "smp/community/list",
    "params": {
        "level": 1   // 0 = coarse, 1 = fine, omit = both levels
    }
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "level": 1,
        "communities": [
            {"community_id": "comm_0", "size": 112, "level": 1},
            {"community_id": "comm_1", "size": 83, "level": 1}
        ],
        "total": 14
    }
}
```

```json
// smp/community/get — Get all nodes in a specific community
{
    "jsonrpc": "2.0",
    "method": "smp/community/get",
    "params": {
        "community_id":    "comm_auth_core",
        "node_types":      ["Function", "Class"],
        "include_bridges": true
    },
    "id": 20
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "community_id": "comm_0",
        "size": 47,
        "nodes": [
            {
                "id": "a1b2c3d4::Function::authenticate_user::15",
                "name": "authenticate_user",
                "type": "Function",
                "file": "src/auth/login.py"
            }
        ],
        "bridges": [
            {
                "source": "a1b2c3d4::Function::authenticate_user::15",
                "target": "b2c3d4e5::Class::UserModel::8",
                "edge_type": "CALLS"
            }
        ]
    },
    "id": 20
}
```

```json
// smp/community/boundaries — Coupling strength between all community pairs.
// Architecture agents use this to understand which domains are tightly coupled
// and identify the exact bridge nodes responsible for cross-domain dependencies.
{
    "jsonrpc": "2.0",
    "method": "smp/community/boundaries",
    "params": {
        "level":        0,      // 0 = coarse module boundaries, 1 = fine boundaries
        "min_coupling": 0.05    // omit pairs below this weight
    },
    "id": 21
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "level": 0,
        "min_coupling": 0.05,
        "boundaries": [
            {
                "from_community": "comm_0",
                "to_community":   "comm_1",
                "edge_count":     83,
                "coupling":       0.61,
                "examples": [
                    {"source": "a1b2::Function::f::1", "target": "c3d4::Class::C::8", "edge_type": "CALLS"}
                ]
            }
        ]
    },
    "id": 21
}
```

---

## Part 2: The Query Engine

### Query Types

| Type | Purpose | Example |
|------|---------|---------|
| **Navigate** | Find specific entities | "Where is `login` defined?" |
| **Trace** | Follow relationships | "What calls `authenticateUser`?" |
| **Context** | Get relevant context | "I'm editing `auth.ts`, what do I need to know?" |
| **Impact** | Assess change impact | "If I delete this, what breaks?" |
| **Locate** | Find by description | "Where is user registration handled?" |
| **Flow** | Trace data/logic path | "How does a request become a DB entry?" |

---

### Query Engine Implementation

```python
# smp/engine/query.py
from collections import deque
from typing import Any

from smp.core.models import EdgeType, GraphNode, LocateParams, NodeType, SearchParams
from smp.store.graph.parser import CodeParser
from smp.store.interfaces import GraphStore


# ── Request Models (msgspec.Struct — zero-copy, schema-validated) ─────────────

class LocateParams(msgspec.Struct):
    query: str = ""
    fields: list[str] = msgspec.field(default_factory=lambda: ["name", "docstring", "tags"])
    node_types: list[str] = msgspec.field(default_factory=list)
    top_k: int = 5

class SearchParams(msgspec.Struct):
    query: str = ""
    match: str = "any"   # "all" = AND, "any" = OR across query terms
    filter: dict[str, Any] = msgspec.field(default_factory=dict)
    top_k: int = 5


# ── Keyword Query Engine ───────────────────────────────────────────────────────

class DefaultQueryEngine:
    """
    Keyword search over the mmap graph store — no vectors, no PageRank, no LLM.

    smp/locate: score terms against name (100/50), docstring (30/15), tags (+10).
    smp/search: score terms against name (+3), node ID (+3), docstring (+2),
                description (+1), file path (+1); match selects AND vs OR.
    Structural expansion (navigate / trace / flow) walks the in-process
    adjacency lists of the MMapGraphStore.
    """

    def __init__(self, graph_store: GraphStore, enricher: Any | None = None):
        self._graph = graph_store
        self._enricher = enricher
```

> The historical sketch in this section (external vector seeds + remote graph walk + composite ranking) did not reflect
> this implementation and has been removed. Vector similarity lives separately in `smp/vector/*`.

---

### The `get_context()` Method (Most Important for Agents)

```python
def get_context(self, file_path: str, scope: str = "edit"):
    """
    Returns the "programmer's mental model" for a file,
    plus a pre-computed summary so agents don't drown in raw data.
    """
    file_node = self.graph.get_node_by_path(file_path)
    imported_by = self.graph.get_relationships(file_node, "IMPORTS", direction="incoming")

    context = {
        "self": file_node,

        "imports": self.graph.get_relationships(
            file_node, "IMPORTS", direction="outgoing"
        ),

        "imported_by": imported_by,

        "defines": self.graph.get_relationships(
            file_node, "DEFINES", direction="outgoing"
        ),

        "related_patterns": self.graph.find_structurally_similar(file_node),

        "entry_points": self.graph.find_entry_points(file_node),

        "data_flow_in":  self.trace_data_flow(file_node, direction="in"),
        "data_flow_out": self.trace_data_flow(file_node, direction="out"),

        # Pre-computed summary — agent reads this first, drills into raw fields only if needed
        "summary": self._build_summary(file_node, imported_by),
    }

    return context

def _build_summary(self, file_node, imported_by: list) -> dict:
    """
    Purely structural computation — no LLM, no generated sentences.
    Every field is a count, enum, or list derived directly from the graph.
    """
    api_layer_files      = self.graph.count_in_package("src/api")
    imported_by_api      = [f for f in imported_by if "src/api" in f.path]
    complexity_scores    = [n.metrics["complexity"] for n in file_node.defines]
    avg_complexity       = round(sum(complexity_scores) / max(len(complexity_scores), 1), 1)
    max_complexity       = max(complexity_scores, default=0)

    return {
        "role":              self._classify_role(file_node),
        "blast_radius":      len(imported_by),
        "api_layer_callers": len(imported_by_api),
        "api_layer_total":   api_layer_files,
        "avg_complexity":    avg_complexity,
        "max_complexity":    max_complexity,
        "exported_symbols":  len(file_node.exports),
        "has_tests":         self.graph.has_tests(file_node),
        "test_files":        self.graph.get_test_files(file_node),
        "is_hot_node":       self.telemetry.is_hot(file_node.id),
        "heat_score":        self.telemetry.heat_score(file_node.id),
        "risk_level":        "high"   if len(imported_by) > 10 or avg_complexity > 8 else
                             "medium" if len(imported_by) > 3  or avg_complexity > 4 else
                             "low",
    }

def _classify_role(self, file_node) -> str:
    """
    Derive file role purely from graph topology — no LLM.

    Rules applied in order (first match wins):
      test        → file path contains /test/ or /spec/, or all defines are Test nodes
      config      → file is a Config node type
      endpoint    → file defines a Function with an HTTP-verb decorator (@get/@post/etc)
                    or path contains /routes/ or /controllers/
      service     → file path contains /services/ and has both incoming + outgoing IMPORTS
      core_utility → blast_radius > 5 (imported by many) and path contains /utils/ or /lib/ or /shared/
      isolated    → blast_radius == 0 and not exported
      module      → default fallback
    """
    path = file_node.path
    if "/test" in path or "/spec" in path:
        return "test"
    if file_node.node_type == "Config":
        return "config"
    decorators = [d for n in file_node.defines for d in n.decorators]
    if any(d in decorators for d in ["@get", "@post", "@put", "@delete", "@patch"]):
        return "endpoint"
    if "/routes" in path or "/controllers" in path:
        return "endpoint"
    if "/services" in path:
        return "service"
    if len(file_node.imported_by) > 5 and any(p in path for p in ["/utils", "/lib", "/shared", "/helpers"]):
        return "core_utility"
    if len(file_node.imported_by) == 0 and not file_node.exports:
        return "isolated"
    return "module"

---

## Part 3: The Protocol (SMP)

### Protocol Specification

**Name:** Structural Memory Protocol (SMP)
**Version:** 1.0
**Transport:** JSON-RPC 2.0 over stdio / HTTP / WebSocket
**Inspired by:** MCP (Model Context Protocol), A2A (Agent-to-Agent)

---

### Protocol Methods

#### 1. Memory Management

```json
// smp/update - Sync codebase state
{
    "jsonrpc": "2.0",
    "method": "smp/update",
    "params": {
        "type": "file_change",
        "file_path": "src/auth/login.ts",
        "content": "...",
        "change_type": "modified" | "created" | "deleted"
    },
    "id": 1
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "status": "success",
        "nodes_added": 3,
        "nodes_updated": 12,
        "nodes_removed": 1,
        "relationships_updated": 8
    },
    "id": 1
}
```

```json
// smp/batch_update - Multiple files at once
{
    "jsonrpc": "2.0",
    "method": "smp/batch_update",
    "params": {
        "changes": [
            {"file_path": "src/auth/login.ts", "content": "...", "change_type": "modified"},
            {"file_path": "src/auth/middleware.ts", "content": "...", "change_type": "created"}
        ]
    },
    "id": 2
}
```

```json
// smp/sync — Merkle-diff sync. Client sends its current root hash and a
// flat map of { file_path → sha256(content) }. Server compares against its
// own Merkle tree and returns exactly which files need to be pushed.
// O(log n) — only walks subtrees where hashes diverge.
{
    "jsonrpc": "2.0",
    "method": "smp/sync",
    "params": {
        "client_root_hash": "e3b0c44298fc",
        "file_hashes": {
            "src/auth/login.ts":      "a3f9c12d",
            "src/auth/register.ts":   "99de12ab",
            "src/utils/crypto.ts":    "c3a1f004",
            "src/db/models/user.ts":  "7f3b9e21"
        }
    },
    "id": 3
}

// Response — server returns the minimal diff, not a full file list
{
    "jsonrpc": "2.0",
    "result": {
        "server_root_hash": "f7c2a19b3d84",
        "in_sync": false,
        "diff": {
            "stale_on_server": [
                {
                    "file": "src/auth/login.ts",
                    "client_hash": "a3f9c12d",
                    "server_hash": "b7d2e91f",
                    "action": "push"      // client is newer — push to server
                }
            ],
            "missing_on_client": [
                {
                    "file": "src/auth/oauth.ts",
                    "server_hash": "44f1c8d9",
                    "action": "pull"      // server has file client doesn't know about
                }
            ],
            "deleted_on_server": [
                {
                    "file": "src/auth/legacy.ts",
                    "action": "remove_from_graph"
                }
            ],
            "unchanged": 2                // count only — no need to list them
        }
    },
    "id": 3
}

// Response — already in sync, nothing to do
{
    "jsonrpc": "2.0",
    "result": {
        "server_root_hash": "e3b0c44298fc",
        "in_sync": true,
        "diff": {
            "stale_on_server": [],
            "missing_on_client": [],
            "deleted_on_server": [],
            "unchanged": 4
        }
    },
    "id": 3
}
```

```json
// smp/merkle/tree — Return the server's full Merkle tree.
// Agents use this to build a local copy for offline diff before connecting.
{
    "jsonrpc": "2.0",
    "method": "smp/merkle/tree",
    "params": {
        "scope": "full"   // "full" | "package:src/auth"
    },
    "id": 4
}

// Response — hierarchical hash tree, mirrors the package/file structure
{
    "jsonrpc": "2.0",
    "result": {
        "root_hash": "f7c2a19b3d84",
        "tree": {
            "src": {
                "hash": "9c4f2a1b",
                "children": {
                    "auth": {
                        "hash": "3d8e7f12",
                        "children": {
                            "login.ts":    {"hash": "b7d2e91f", "node_count": 4},
                            "register.ts": {"hash": "99de12ab", "node_count": 3},
                            "oauth.ts":    {"hash": "44f1c8d9", "node_count": 6}
                        }
                    },
                    "utils": {
                        "hash": "1a3c9f00",
                        "children": {
                            "crypto.ts": {"hash": "c3a1f004", "node_count": 5}
                        }
                    }
                }
            }
        }
    },
    "id": 4
}
```

---

#### 1b. Secure Index Distribution

A new agent or a new SMP server instance does not need to re-index the entire codebase from scratch. The current server exports a cryptographically signed snapshot of its index. The recipient compares Merkle root hashes — if they match, it imports directly. If they differ, it only re-indexes the diverging subtrees.

```
┌─────────────────┐           ┌─────────────────┐
│  SMP Server A   │  export   │  SMP Server B   │
│  (source)       │──────────▶│  (new instance) │
│                 │  signed   │                 │
│  root: f7c2a19b │  snapshot │  1. verify sig  │
│                 │           │  2. compare root │
└─────────────────┘           │  3a. match →    │
                               │     import all  │
                               │  3b. differ →   │
                               │     sync diff   │
                               └─────────────────┘
```

```json
// smp/index/export — Package the current index as a signed, portable snapshot.
// Used for fast agent onboarding and multi-instance distribution.
{
    "jsonrpc": "2.0",
    "method": "smp/index/export",
    "params": {
        "scope": "full",              // "full" | "package:<path>"
        "signing_key_id": "key_prod_01"
    },
    "id": 5
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "snapshot_id": "snap_4f8a2c",
        "root_hash": "f7c2a19b3d84",
        "scope": "full",
        "node_count": 1240,
        "edge_count": 8430,
        "signed_at": "2025-02-15T10:00:00Z",
        "signature": "sha256:a1b2c3...",
        "export_url": "smp://snapshots/snap_4f8a2c.tar.zst"
    },
    "id": 5
}
```

```json
// smp/index/import — Load a signed snapshot into this server instance.
// Verifies signature and root hash before touching the graph.
{
    "jsonrpc": "2.0",
    "method": "smp/index/import",
    "params": {
        "snapshot_id": "snap_4f8a2c",
        "source_url": "smp://snapshots/snap_4f8a2c.tar.zst",
        "expected_root_hash": "f7c2a19b3d84",
        "verify_signature": true
    },
    "id": 6
}

// Response: hashes match → full import, no re-indexing needed
{
    "jsonrpc": "2.0",
    "result": {
        "status": "imported",
        "root_hash_verified": true,
        "signature_verified": true,
        "nodes_imported": 1240,
        "edges_imported": 8430,
        "re_indexed_files": 0,
        "duration_ms": 840
    },
    "id": 6
}

// Response: hashes differ → partial re-index of diverging subtrees only
{
    "jsonrpc": "2.0",
    "result": {
        "status": "partial_import",
        "root_hash_verified": false,
        "signature_verified": true,
        "nodes_imported": 1218,
        "edges_imported": 8390,
        "diverging_packages": ["src/auth", "src/api"],
        "re_indexed_files": 7,
        "duration_ms": 2310
    },
    "id": 6
}

// Response: signature invalid → rejected entirely
{
    "jsonrpc": "2.0",
    "error": {
        "code": -32010,
        "message": "signature_invalid",
        "data": {"snapshot_id": "snap_4f8a2c", "key_id": "key_prod_01"}
    },
    "id": 6
}
```

---

#### 2. Structural Queries

```json
// smp/navigate - Find entity and basic info
{
    "jsonrpc": "2.0",
    "method": "smp/navigate",
    "params": {
        "query": "authenticateUser",
        "include_relationships": true
    },
    "id": 4
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "entity": {
            "id": "func_authenticate_user",
            "type": "Function",
            "file": "src/auth/login.ts",
            "signature": "authenticateUser(email: string, password: string): Promise<Token>",
            "purpose": "Handles user authentication..."
        },
        "relationships": {
            "calls": ["hashPassword", "compareHash", "generateToken"],
            "called_by": ["loginRoute", "test_auth"],
            "depends_on": ["UserModel", "TokenService"]
        }
    },
    "id": 4
}
```

```json
// smp/trace - Follow relationship chain
{
    "jsonrpc": "2.0",
    "method": "smp/trace",
    "params": {
        "start": "func_authenticate_user",
        "relationship": "CALLS",
        "depth": 3,
        "direction": "outgoing"
    },
    "id": 5
}

// Response: Returns the call graph as a tree
{
    "jsonrpc": "2.0",
    "result": {
        "root": "authenticateUser",
        "tree": {
            "authenticateUser": {
                "calls": {
                    "hashPassword": {"calls": {"bcrypt.hash": {}}},
                    "compareHash": {"calls": {"bcrypt.compare": {}}},
                    "generateToken": {"calls": {"jwt.sign": {}}}
                }
            }
        }
    },
    "id": 5
}
```

---

#### 3. Context Queries (Proactive)

```json
// smp/context - Get editing context
{
    "jsonrpc": "2.0",
    "method": "smp/context",
    "params": {
        "file_path": "src/auth/login.ts",
        "scope": "edit",  // "edit" | "create" | "debug" | "review"
        "depth": 2
    },
    "id": 6
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "summary": {
            "role": "core_utility",
            "blast_radius": 12,
            "api_layer_callers": 7,
            "api_layer_total": 12,
            "avg_complexity": 5.2,
            "max_complexity": 9,
            "exported_symbols": 3,
            "has_tests": true,
            "test_files": ["tests/auth.test.ts"],
            "is_hot_node": true,
            "heat_score": 96,
            "risk_level": "high"
        },
        "self": {
            "id": "file_auth_login_ts",
            "path": "src/auth/login.ts",
            "language": "typescript",
            "lines": 120,
            "source_hash": "a3f9c12d"
        },
        "imports": [
            {"file": "src/utils/crypto.ts", "items": ["hashPassword", "compareHash"]},
            {"file": "src/db/models/user.ts", "items": ["UserModel"]}
        ],
        "imported_by": [
            {"file": "src/api/routes.ts"},
            {"file": "src/middleware/auth.ts"},
            {"file": "src/api/admin.ts"}
        ],
        "defines": {
            "functions": [
                {"id": "func_authenticate_user", "name": "authenticateUser", "complexity": 9, "exported": true},
                {"id": "func_refresh_token",     "name": "refreshToken",     "complexity": 4, "exported": true}
            ],
            "classes": [
                {"id": "class_AuthService", "name": "AuthService", "method_count": 3, "exported": true}
            ]
        },
        "structurally_similar": [
            {"file": "src/api/users.ts",   "shared_imports": 3, "shared_node_types": ["Function", "Class"]},
            {"file": "src/api/session.ts", "shared_imports": 2, "shared_node_types": ["Function"]}
        ],
        "entry_points": ["func_authenticate_user", "func_refresh_token"],
        "data_flow_in": [
            {"from": "src/api/routes.ts", "via": "loginRoute", "carries": "Request"}
        ],
        "data_flow_out": [
            {"to": "src/db/models/user.ts", "via": "UserModel.findByEmail", "carries": "UserRecord"}
        ]
    },
    "id": 6
}
```

```json
// smp/impact - Assess change impact
{
    "jsonrpc": "2.0",
    "method": "smp/impact",
    "params": {
        "entity": "func_authenticate_user",
        "change_type": "signature_change" | "delete" | "move"
    },
    "id": 7
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "affected_files": [
            "src/api/routes.ts",
            "tests/auth.test.ts",
            "src/middleware/auth.ts"
        ],
        "affected_functions": [
            {"id": "func_login_route",            "file": "src/api/routes.ts",       "relationship": "CALLS"},
            {"id": "func_test_authenticate_user", "file": "tests/auth.test.ts",      "relationship": "TESTS"},
            {"id": "func_auth_middleware",         "file": "src/middleware/auth.ts",  "relationship": "CALLS"}
        ],
        "severity": "high",
        "required_updates": [
            {
                "file": "src/api/routes.ts",
                "function": "loginRoute",
                "reason": "CALLS",
                "change_type": "signature_change"
            },
            {
                "file": "tests/auth.test.ts",
                "function": "test_authenticate_user",
                "reason": "TESTS",
                "change_type": "signature_change"
            }
        ]
    },
    "id": 7
}
```

---

#### 4. Keyword Code Discovery (`smp/locate`)

`smp/locate` is the primary code discovery method. It scores query terms against entity names, docstrings, and tags —
no vectors, no LLM at any stage:

```
MATCH:  split the query into lowercase terms; score every node in the mmap graph store.
SCORE:  all terms in name → 100 · any term in name → 50 · all terms in docstring → 30 ·
        any term in docstring → 15 · any term in a tag → +10.
FILTER: narrow by `fields` (default ["name", "docstring", "tags"]) and `node_types`.
RANK:   sort by descending score, return top_k with `matched_on` provenance.
EXPAND: feed any hit into smp/navigate, smp/trace, or smp/context to walk the structural graph.
```

```json
// Request
{
    "jsonrpc": "2.0",
    "method": "smp/locate",
    "params": {
        "query":      "user registration",
        "fields":     ["name", "docstring", "tags"],
        "node_types": ["Function", "Class"],
        "top_k":      10
    },
    "id": 8
}

// Response (Accept: application/json)
{
    "jsonrpc": "2.0",
    "result": {
        "matches": [
            {
                "entity":      "register_user",
                "file":        "src/auth/register.py",
                "matched_on":  "name",
                "docstring":   "Create a new user account and send a verification email.",
                "tags":        ["auth", "registration"]
            },
            {
                "entity":      "UserService",
                "file":        "src/services/user.py",
                "matched_on":  "docstring",
                "docstring":   "Manage user CRUD operations including registration.",
                "tags":        ["user", "service"]
            },
            {
                "entity":      "send_verification_email",
                "file":        "src/notifications/email.py",
                "matched_on":  "name, tags",
                "docstring":   "Send an account verification link to a new user.",
                "tags":        ["email", "notifications"]
            }
        ]
    },
    "id": 8
}
```

---

#### 5. Flow Analysis

```json
// smp/flow - Trace execution/data flow
{
    "jsonrpc": "2.0",
    "method": "smp/flow",
    "params": {
        "start": "api_route_login",
        "end": "database_write_user",
        "flow_type": "data" | "execution"
    },
    "id": 9
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "path": [
            {"node": "api_route_login",        "type": "endpoint",  "file": "src/api/routes.ts"},
            {"node": "auth_middleware",          "type": "middleware", "file": "src/middleware/auth.ts"},
            {"node": "authenticateUser",         "type": "function",  "file": "src/auth/login.ts"},
            {"node": "UserModel.findByEmail",    "type": "method",    "file": "src/db/models/user.ts"},
            {"node": "generateToken",            "type": "function",  "file": "src/auth/login.ts"},
            {"node": "response_json",            "type": "output",    "file": "src/api/routes.ts"}
        ],
        "type_transitions": [
            {"from_node": "api_route_login",     "to_node": "authenticateUser",      "param_types": ["Request"], "return_type": "Promise<Token>"},
            {"from_node": "authenticateUser",    "to_node": "UserModel.findByEmail", "param_types": ["string"],  "return_type": "Promise<UserRecord>"},
            {"from_node": "authenticateUser",    "to_node": "generateToken",         "param_types": ["UserRecord"], "return_type": "Promise<Token>"}
        ]
    },
    "id": 9
}
```

---

#### 6. Structural Diff

Before writing, an agent needs to know *exactly* what changed between the current version and its proposed version — at the node level, not the line level.

```json
// smp/diff - Compare current graph state of a file against proposed new content
{
    "jsonrpc": "2.0",
    "method": "smp/diff",
    "params": {
        "file_path": "src/auth/login.ts",
        "proposed_content": "..."
    },
    "id": 10
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "nodes_added": [
            {"id": "func_check_rate_limit", "type": "Function", "name": "checkRateLimit"}
        ],
        "nodes_removed": [],
        "nodes_modified": [
            {
                "id": "func_authenticate_user",
                "changes": {
                    "signature_changed": false,
                    "body_changed": true,
                    "complexity_delta": +2,
                    "calls_added": ["func_check_rate_limit"],
                    "calls_removed": []
                }
            }
        ],
        "relationships_added": [
            {"edge": "CALLS", "from": "func_authenticate_user", "to": "func_check_rate_limit"}
        ],
        "relationships_removed": []
    },
    "id": 10
}
```

---

#### 7. Multi-File Plan

Before a complex multi-file task, the agent declares its full plan upfront. SMP validates scope, detects inter-file conflicts, and returns a risk-ranked execution order.

```json
// smp/plan - Validate and rank a multi-file task before execution
{
    "jsonrpc": "2.0",
    "method": "smp/plan",
    "params": {
        "session_id": "ses_4f8a2c",
        "task": "Refactor AuthService to support OAuth in addition to password auth",
        "intended_writes": [
            "src/auth/login.ts",
            "src/auth/oauth.ts",
            "src/middleware/auth.ts",
            "src/types/token.ts"
        ]
    },
    "id": 11
}

// Response — execution order sorted by dependency: write leaves first, roots last
{
    "jsonrpc": "2.0",
    "result": {
        "execution_order": [
            {
                "step": 1,
                "file": "src/types/token.ts",
                "dependants_in_plan": 0,
                "dependencies_in_plan": 0,
                "blast_radius": 2,
                "risk_level": "low"
            },
            {
                "step": 2,
                "file": "src/auth/oauth.ts",
                "dependants_in_plan": 1,
                "dependencies_in_plan": 0,
                "blast_radius": 0,
                "risk_level": "low",
                "is_new_file": true
            },
            {
                "step": 3,
                "file": "src/auth/login.ts",
                "dependants_in_plan": 1,
                "dependencies_in_plan": 1,
                "depends_on_steps": [1],
                "blast_radius": 12,
                "is_hot_node": true,
                "heat_score": 96,
                "risk_level": "high"
            },
            {
                "step": 4,
                "file": "src/middleware/auth.ts",
                "dependants_in_plan": 0,
                "dependencies_in_plan": 2,
                "depends_on_steps": [2, 3],
                "blast_radius": 5,
                "risk_level": "medium"
            }
        ],
        "inter_file_conflicts": [],
        "external_files_at_risk": [
            "src/api/routes.ts",
            "tests/auth.test.ts"
        ]
    },
    "id": 11
}
```

---

#### 8. Conflict Detection

Check if two agents' scopes overlap before either starts writing.

```json
// smp/conflict - Detect scope overlap between two planned sessions
{
    "jsonrpc": "2.0",
    "method": "smp/conflict",
    "params": {
        "session_a": "ses_4f8a2c",
        "session_b": "ses_7c1d9f"
    },
    "id": 12
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "conflict": true,
        "overlapping_files": ["src/auth/login.ts"],
        "overlapping_nodes": ["func_authenticate_user"],
        "session_modes": {
            "ses_4f8a2c": "write",
            "ses_7c1d9f": "read"
        },
        "write_session": "ses_4f8a2c"
    },
    "id": 12
}

// No conflict
{
    "jsonrpc": "2.0",
    "result": {
        "conflict": false
    },
    "id": 12
}
```

---

#### 9. Graph Explanation

Agents often need to understand *why* a dependency exists — not just that it does. `smp/graph/why` traces the shortest structural path between two nodes and returns it as a human-readable chain.

```json
// smp/graph/why - Explain the dependency path between two nodes
{
    "jsonrpc": "2.0",
    "method": "smp/graph/why",
    "params": {
        "from": "src/api/routes.ts",
        "to": "src/utils/crypto.ts"
    },
    "id": 13
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "path_length": 3,
        "chain": [
            {"node": "src/api/routes.ts",    "edge": "IMPORTS",  "target": "src/auth/login.ts"},
            {"node": "src/auth/login.ts",    "edge": "IMPORTS",  "target": "src/utils/crypto.ts"}
        ],
        "readable": "routes.ts → imports → login.ts → imports → crypto.ts"
    },
    "id": 13
}

// No path found
{
    "jsonrpc": "2.0",
    "result": {
        "path_length": null,
        "chain": [],
        "readable": "No dependency path exists between these two nodes"
    },
    "id": 13
}
```

---

### Event Notifications (Server → Agent)

```json
// Notification: Memory updated
{
    "jsonrpc": "2.0",
    "method": "smp/notification",
    "params": {
        "type": "memory_updated",
        "changes": {
            "files_affected": ["src/auth/login.ts"],
            "structural_changes": ["func_authenticate_user modified"],
            "semantic_changes": ["purpose re-enriched"]
        }
    }
}
```

```json
// Notification: Conflict detected
{
    "jsonrpc": "2.0",
    "method": "smp/notification",
    "params": {
        "type": "conflict_detected",
        "severity": "warning",
        "message": "File modified by external process, memory may be stale",
        "file": "src/auth/login.ts"
    }
}
```

---

## Part 4: Agent Safety Protocol

> The core idea: **the agent must talk to SMP before it touches anything.** SMP acts as the guardrail layer between the agent and the codebase — enforcing scope, surfacing danger, and keeping a full audit trail of every write.

---

### The Agent Write Lifecycle (MVCC + Sandbox)

File-level locking (`smp/lock`) is the sequential model — one agent, one file at a time. For swarms of parallel agents, SMP uses **MVCC**: each agent works against a specific `commit_sha` snapshot in its own isolated sandbox. No agent blocks another. Merge conflicts are resolved at PR time, not at lock-acquisition time.

```
Agent receives task
        │
        ▼
┌──────────────────────┐
│  smp/session/open    │  ← declare intent + commit_sha snapshot
└─────────┬────────────┘
          │
          ▼
┌──────────────────────┐
│  smp/sandbox/spawn   │  ← get isolated microVM, CoW filesystem, firewalled network
└─────────┬────────────┘
          │
          ▼
┌──────────────────────┐
│  smp/guard/check     │  ← pre-flight: coverage gaps, hot nodes, blast radius
└─────────┬────────────┘
          │
     ┌────┴────┐
  CLEAR      RED_ALERT ──► fix blocking condition, re-check
     │           BLOCKED ──► abort
     ▼
┌──────────────────────┐
│  smp/dryrun          │  ← structural diff against snapshot — what would break?
└─────────┬────────────┘
          │
     ┌────┴──────┐
   SAFE        BREAKING ──► fix callers first, re-run
     │
     ▼
  WRITE FILE (inside sandbox)
     │
     ▼
┌──────────────────────┐
│  smp/sandbox/execute │  ← run tests, capture eBPF runtime trace
└─────────┬────────────┘
          │
     ┌────┴──────────┐
  PASS           FAIL ──► read stderr/trace, self-correct, re-execute
     │
     ▼
┌──────────────────────┐
│  smp/verify/integrity│  ← AST data-flow check + mutation test gate
└─────────┬────────────┘
          │
     ┌────┴───────────┐
  PASSED          SURVIVING_MUTANT ──► tighten assertions, re-verify
     │
     ▼
┌──────────────────────┐
│  smp/update          │  ← sync graph memory with new file state
└─────────┬────────────┘
          │
          ▼
┌──────────────────────┐
│  smp/handoff/pr      │  ← pass to reviewer agent or file PR directly
└─────────┬────────────┘
          │
          ▼
┌──────────────────────┐
│  smp/session/close   │  ← commit audit log, destroy sandbox
└──────────────────────┘
```

---

#### 1. Session Management

Sessions and locks are persisted directly in the Graph DB — not in memory. If the SMP server restarts, all active sessions, locks, and checkpoints survive. Agents reconnect and continue without losing their write guards.

**Persistence schema in Graph DB:**

```
(:Session {id, agent_id, task, scope, mode, status, opened_at, expires_at})
(:Lock    {file, held_by_session, acquired_at, expires_at})
(:Checkpoint {id, session_id, files_snapshotted, snapshot_at, content_hash})

(:Session)-[:HOLDS]->(:Lock)
(:Session)-[:HAS_CHECKPOINT]->(:Checkpoint)
```

```json
// smp/session/open — declare intent before touching the codebase
{
    "jsonrpc": "2.0",
    "method": "smp/session/open",
    "params": {
        "agent_id":   "coder_agent_01",
        "task":       "Add rate limiting to the login endpoint",
        "scope": [
            "src/auth/login.ts",
            "src/middleware/rateLimit.ts"
        ],
        "mode":       "write",      // "read" | "write"
        "commit_sha": "a1b2c3d4",   // graph snapshot this session operates against
        "concurrency": "mvcc"       // "mvcc" (parallel, sandbox-isolated) | "exclusive" (file-locked, sequential)
    },
    "id": 15
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "session_id": "ses_4f8a2c",
        "commit_sha": "a1b2c3d4",
        "concurrency": "mvcc",
        "granted_scope": [
            "src/auth/login.ts",
            "src/middleware/rateLimit.ts"
        ],
        "denied_scope": [],
        "scope_analysis": {
            "src/auth/login.ts":           {"blast_radius": 12, "is_hot_node": true,  "heat_score": 96, "risk_level": "high"},
            "src/middleware/rateLimit.ts": {"blast_radius": 3,  "is_hot_node": false, "heat_score": 12, "risk_level": "medium"}
        },
        "safety_level": "elevated",
        "expires_at": "2025-02-15T11:30:00Z"
    },
    "id": 15
}
```

```json
// smp/session/recover — reconnect to a persisted session after a server restart or crash
{
    "jsonrpc": "2.0",
    "method": "smp/session/recover",
    "params": {
        "session_id": "ses_4f8a2c",
        "agent_id": "coder_agent_01"
    },
    "id": 16
}

// Response — session is intact, locks re-confirmed
{
    "jsonrpc": "2.0",
    "result": {
        "session_id": "ses_4f8a2c",
        "status": "recovered",
        "scope": ["src/auth/login.ts", "src/middleware/rateLimit.ts"],
        "locks_held": ["src/auth/login.ts"],
        "checkpoints": ["chk_3a7f91"],
        "events_so_far": 4,
        "expires_at": "2025-02-15T11:30:00Z"
    },
    "id": 16
}

// Response — session expired during downtime, must re-open
{
    "jsonrpc": "2.0",
    "result": {
        "status": "expired",
        "reason": "ttl_elapsed",
        "last_checkpoint": "chk_3a7f91",
        "last_checkpoint_at": "2025-02-15T10:45:00Z",
        "files_snapshotted": ["src/auth/login.ts"]
    },
    "id": 16
}
```

```json
// smp/session/close — commit the session, release locks, write audit log
{
    "jsonrpc": "2.0",
    "method": "smp/session/close",
    "params": {
        "session_id": "ses_4f8a2c",
        "status": "completed"   // "completed" | "aborted" | "rolled_back"
    },
    "id": 17
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "session_id": "ses_4f8a2c",
        "files_written": ["src/auth/login.ts"],
        "files_read": ["src/middleware/rateLimit.ts"],
        "duration_ms": 4200,
        "audit_log_id": "aud_9b3e1a"
    },
    "id": 17
}
```

---

#### 2. Pre-Flight Guard Check

Before writing, the agent asks SMP: *is it safe to touch this?* SMP checks scope, locks, concurrent agents, and — critically — whether the specific function being changed has test coverage. If a high-complexity function has zero test coverage, the guard returns `red_alert` and blocks the write.

```json
// smp/guard/check — pre-flight safety check before writing a file
{
    "jsonrpc": "2.0",
    "method": "smp/guard/check",
    "params": {
        "session_id": "ses_4f8a2c",
        "target": "src/auth/login.ts",
        "intended_change": "modify_function:authenticateUser",
        "coverage_report": "coverage/lcov.info"   // optional: path to lcov/cobertura report
    },
    "id": 19
}

// Response: CLEAR
{
    "jsonrpc": "2.0",
    "result": {
        "verdict": "clear",
        "target": "src/auth/login.ts",
        "checks": {
            "in_declared_scope":      true,
            "locked_by_other_agent":  false,
            "is_hot_node":            false,
            "heat_score":             18,
            "has_tests":              true,
            "test_files":             ["tests/auth.test.ts"],
            "function_coverage": {
                "authenticateUser": {"covered": true, "coverage_pct": 87}
            },
            "caller_count":           3,
            "blast_radius":           3,
            "is_public_api":          true
        },
        "safety_level": "standard"
    },
    "id": 19
}

// Response: RED ALERT — high-complexity function, zero test coverage
{
    "jsonrpc": "2.0",
    "result": {
        "verdict": "red_alert",
        "target": "src/auth/login.ts",
        "checks": {
            "in_declared_scope":     true,
            "locked_by_other_agent": false,
            "is_hot_node":           true,
            "heat_score":            96,
            "has_tests":             true,
            "test_files":            ["tests/auth.test.ts"],
            "function_coverage": {
                "authenticateUser": {"covered": false, "coverage_pct": 0}
            },
            "caller_count":          12,
            "blast_radius":          12,
            "is_public_api":         true
        },
        "safety_level": "elevated",
        "blocking": [
            {"code": "ZERO_COVERAGE",  "node_id": "func_authenticate_user", "complexity": 9, "coverage_pct": 0},
            {"code": "HOT_NODE",       "node_id": "func_authenticate_user", "heat_score": 96, "caller_count": 12}
        ],
        "unblock_conditions": [
            {"code": "ZERO_COVERAGE", "action": "add_tests", "target_node": "func_authenticate_user", "min_coverage_pct": 60}
        ]
    },
    "id": 19
}

// Response: BLOCKED — hard stop, no conditions
{
    "jsonrpc": "2.0",
    "result": {
        "verdict": "blocked",
        "target": "src/auth/login.ts",
        "reasons": [
            "File is outside declared session scope",
            "Locked by session ses_7c1d9f (agent: reviewer_agent_02)"
        ]
    },
    "id": 19
}
```

**Verdict levels:**

| Verdict | Meaning | Agent action |
|---|---|---|
| `clear` | Safe to proceed | Continue to dryrun |
| `red_alert` | High risk, remediable | Fix the blocking reason, re-check |
| `blocked` | Hard stop | Abort — do not proceed |

---

#### 3. Dry Run

Simulate the write. SMP resolves the structural impact of the proposed change without writing anything to disk — returning exactly which nodes, files, and callers would be affected.

```json
// smp/dryrun — simulate a write and see what breaks
{
    "jsonrpc": "2.0",
    "method": "smp/dryrun",
    "params": {
        "session_id": "ses_4f8a2c",
        "file_path": "src/auth/login.ts",
        "proposed_content": "...",
        "change_summary": "Added rate limit check before credential validation"
    },
    "id": 18
}

// Response: SAFE
{
    "jsonrpc": "2.0",
    "result": {
        "structural_delta": {
            "nodes_added": 1,
            "nodes_modified": 1,
            "nodes_removed": 0,
            "signature_changed": false
        },
        "impact": {
            "affected_files": [],
            "broken_callers": [],
            "test_coverage_delta": "unchanged"
        },
        "verdict": "safe",
        "risks": []
    },
    "id": 18
}

// Response: BREAKING change detected
{
    "jsonrpc": "2.0",
    "result": {
        "structural_delta": {
            "nodes_modified": 1,
            "signature_changed": true
        },
        "impact": {
            "affected_files": ["src/api/routes.ts", "tests/auth.test.ts"],
            "broken_callers": [
                {
                    "function": "loginRoute",
                    "file": "src/api/routes.ts",
                    "expected_return_type": "Promise<Token>",
                    "actual_return_type":   "Promise<{token, retryAfter}>"
                }
            ],
            "broken_tests": [
                {
                    "function": "test_authenticate_user",
                    "file": "tests/auth.test.ts",
                    "expected_return_type": "Promise<Token>",
                    "actual_return_type":   "Promise<{token, retryAfter}>"
                }
            ]
        },
        "verdict": "breaking"
    },
    "id": 18
}
```

---

#### 4. Checkpoint & Rollback

Snapshot the structural state of any file before writing. If the agent's edit produces bad output, it can roll back to the snapshot in one call.

```json
// smp/checkpoint — snapshot state before a risky write
{
    "jsonrpc": "2.0",
    "method": "smp/checkpoint",
    "params": {
        "session_id": "ses_4f8a2c",
        "files": ["src/auth/login.ts"]
    },
    "id": 19
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "checkpoint_id": "chk_3a7f91",
        "files_snapshotted": ["src/auth/login.ts"],
        "snapshot_at": "2025-02-15T10:45:00Z"
    },
    "id": 19
}
```

```json
// smp/rollback — revert to a checkpoint
{
    "jsonrpc": "2.0",
    "method": "smp/rollback",
    "params": {
        "session_id": "ses_4f8a2c",
        "checkpoint_id": "chk_3a7f91"
    },
    "id": 20
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "status": "rolled_back",
        "files_restored": ["src/auth/login.ts"],
        "memory_resynced": true
    },
    "id": 20
}
```

---

#### 5. Concurrency: MVCC vs File Locks

Two concurrency modes. Choose at `session/open` time.

**MVCC (default for swarms):** Each agent operates against its own `commit_sha` snapshot. No agent can block another. Multiple agents work in parallel on the same file simultaneously — conflicts surface at `smp/handoff/pr` as standard merge conflicts, resolved by the reviewer agent or a human. This is the model for autonomous agent swarms.

**Exclusive locks (sequential writes):** The original file-lock model. Use when an operation *must* be the only writer and ordering matters — e.g. a schema migration that must complete before any other agent reads the new shape.

```json
// smp/lock — claim exclusive write access (sequential mode only)
// Not needed in MVCC mode — sandbox isolation replaces this
{
    "jsonrpc": "2.0",
    "method": "smp/lock",
    "params": {
        "session_id": "ses_4f8a2c",
        "files": ["src/db/migrations/0012_add_user_role.ts"]
    },
    "id": 21
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "granted": ["src/db/migrations/0012_add_user_role.ts"],
        "denied":  []
    },
    "id": 21
}
```

```json
// smp/unlock — release locks (also released automatically on session/close)
{
    "jsonrpc": "2.0",
    "method": "smp/unlock",
    "params": {
        "session_id": "ses_4f8a2c",
        "files": ["src/db/migrations/0012_add_user_role.ts"]
    },
    "id": 22
}
```

---

#### 6. Audit Log

Full record of every agent session — what was intended, what was read, what was written, what was rolled back.

```json
// smp/audit/get — retrieve the log for a session
{
    "jsonrpc": "2.0",
    "method": "smp/audit/get",
    "params": {
        "audit_log_id": "aud_9b3e1a"
    },
    "id": 23
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "audit_log_id": "aud_9b3e1a",
        "agent_id": "coder_agent_01",
        "task": "Add rate limiting to the login endpoint",
        "session_id": "ses_4f8a2c",
        "opened_at": "2025-02-15T10:44:00Z",
        "closed_at": "2025-02-15T10:45:10Z",
        "status": "completed",
        "events": [
            {"t": "10:44:01", "method": "smp/guard/check",  "target": "src/auth/login.ts", "result": "clear"},
            {"t": "10:44:02", "method": "smp/dryrun",        "target": "src/auth/login.ts", "result": "safe"},
            {"t": "10:44:03", "method": "smp/checkpoint",   "files": ["src/auth/login.ts"], "checkpoint_id": "chk_3a7f91"},
            {"t": "10:44:05", "method": "smp/lock",          "files": ["src/auth/login.ts"], "result": "granted"},
            {"t": "10:44:08", "method": "FILE_WRITE",        "file": "src/auth/login.ts"},
            {"t": "10:44:09", "method": "smp/update",        "file": "src/auth/login.ts", "result": "success"},
            {"t": "10:44:10", "method": "smp/unlock",        "files": ["src/auth/login.ts"]}
        ]
    },
    "id": 23
}
```

---

#### Agent Safety Notifications (Server → Agent)

```json
// lock collision — another agent wants the same file
{
    "jsonrpc": "2.0",
    "method": "smp/notification",
    "params": {
        "type": "lock_conflict",
        "severity": "warning",
        "file": "src/auth/login.ts",
        "held_by_session": "ses_7c1d9f",
        "held_by_agent": "reviewer_agent_02"
    }
}
```

```json
// scope violation — agent tried to write outside its declared scope
{
    "jsonrpc": "2.0",
    "method": "smp/notification",
    "params": {
        "type": "scope_violation",
        "severity": "error",
        "session_id": "ses_4f8a2c",
        "attempted_file": "src/db/models/user.ts",
        "declared_scope": ["src/auth/login.ts", "src/middleware/rateLimit.ts"]
    }
}
```

```json
// session expired — agent took too long, locks auto-released
{
    "jsonrpc": "2.0",
    "method": "smp/notification",
    "params": {
        "type": "session_expired",
        "severity": "error",
        "session_id": "ses_4f8a2c",
        "expired_at": "2025-02-15T11:30:00Z",
        "locks_released": ["src/auth/login.ts"]
    }
}
```

---

## Part 5: Dependency Telemetry

Telemetry tracks *how nodes change over time*, not just their current state. The key insight: a function that changes frequently AND has many callers is a **Hot Node** — high blast radius, high churn. Any agent touching a Hot Node automatically gets an elevated `safety_level` on its session.

---

#### smp/telemetry/record — Record a node change event

Called automatically by `smp/update` on every file write. No manual agent call needed.

```json
// Internal — fired by smp/update on every successful write
{
    "jsonrpc": "2.0",
    "method": "smp/telemetry/record",
    "params": {
        "node_id": "func_authenticate_user",
        "event": "modified",
        "session_id": "ses_4f8a2c",
        "agent_id": "coder_agent_01",
        "timestamp": "2025-02-15T10:44:08Z"
    },
    "id": 30
}
```

---

#### smp/telemetry/hot — Get hot nodes in the graph

```json
// smp/telemetry/hot — list nodes with high churn AND high dependency count
{
    "jsonrpc": "2.0",
    "method": "smp/telemetry/hot",
    "params": {
        "scope": "full",
        "window_days": 30,
        "min_changes": 5,
        "min_callers": 5
    },
    "id": 31
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "hot_nodes": [
            {
                "node_id": "func_authenticate_user",
                "file": "src/auth/login.ts",
                "changes_in_window": 8,
                "caller_count": 12,
                "heat_score": 96,    // (changes × callers), normalized 0–100
                "last_changed_by": "coder_agent_01",
                "last_changed_at": "2025-02-15T10:44:08Z"
            },
            {
                "node_id": "class_UserModel",
                "file": "src/db/models/user.ts",
                "changes_in_window": 6,
                "caller_count": 21,
                "heat_score": 126,
                "last_changed_by": "coder_agent_03",
                "last_changed_at": "2025-02-14T09:11:00Z"
            }
        ]
    },
    "id": 31
}
```

---

#### smp/telemetry/node — Full change history for a specific node

```json
// smp/telemetry/node — change history for a single node
{
    "jsonrpc": "2.0",
    "method": "smp/telemetry/node",
    "params": {
        "node_id": "func_authenticate_user",
        "window_days": 90
    },
    "id": 32
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "node_id": "func_authenticate_user",
        "total_changes": 14,
        "unique_agents": ["coder_agent_01", "coder_agent_03"],
        "history": [
            {"timestamp": "2025-02-15T10:44:08Z", "agent": "coder_agent_01", "session": "ses_4f8a2c", "event": "modified"},
            {"timestamp": "2025-02-10T14:22:00Z", "agent": "coder_agent_03", "session": "ses_1a2b3c", "event": "modified"}
        ],
        "heat_score": 96,
        "stability": "unstable"   // "stable" | "moderate" | "unstable"
    },
    "id": 32
}
```

---

#### Automatic Safety Escalation

When a session opens and any file in its declared scope contains a Hot Node, `smp/session/open` automatically sets `safety_level: elevated`. Elevated sessions must complete `smp/guard/check` → `smp/dryrun` → `smp/checkpoint` in sequence — no shortcuts allowed.

```json
// smp/session/open response when scope contains hot nodes
{
    "jsonrpc": "2.0",
    "result": {
        "session_id": "ses_9x7y6z",
        "granted_scope": ["src/auth/login.ts"],
        "safety_level": "elevated",    // auto-escalated — hot node in scope
        "hot_nodes_in_scope": [
            {
                "node_id": "func_authenticate_user",
                "heat_score": 96,
                "caller_count": 12,
                "changes_in_window": 8
            }
        ],
        "expires_at": "2025-02-15T11:30:00Z"
    },
    "id": 15
}
```

---

## Part 6: Sandbox Runtime

Every agent write session runs inside an ephemeral, network-isolated container. The sandbox is the physical boundary that makes autonomy safe — the agent can run, fail, self-correct, and iterate without ever touching live infrastructure, live APIs, or other agents' work.

---

#### smp/sandbox/spawn — Request an isolated execution environment

Spawns a microVM or Docker container from a specific `commit_sha`. The container gets a Copy-on-Write clone of the filesystem state at that SHA, so multiple agents can each have their own independent snapshot without duplicating storage. Network egress is hard-firewalled — only package registries are reachable.

```json
// Request
{
    "jsonrpc": "2.0",
    "method": "smp/sandbox/spawn",
    "params": {
        "session_id":     "ses_4f8a2c",
        "commit_sha":     "a1b2c3d4",
        "image":          "node:20-alpine",
        "services":       ["postgres:15", "redis:7"],
        "cow_fs_clone":   true,
        "inject_ebpf":    true
    },
    "id": 101
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "sandbox_id":       "box_99x",
        "status":           "ready",
        "commit_sha":       "a1b2c3d4",
        "services_started": ["postgres:15", "redis:7"],
        "network": {
            "egress_policy":    "registry_only",
            "allowed_registries": ["registry.npmjs.org", "pypi.org"]
        },
        "ebpf_injected":    true,
        "spawned_at":       "2025-02-15T10:44:00Z"
    },
    "id": 101
}
```

---

#### smp/sandbox/execute — Run a command, capture output and eBPF trace

Runs any shell command inside the sandbox. If `inject_ebpf` was set on spawn, the response includes new `CALLS_RUNTIME` edges discovered during the execution, which SMP automatically injects into the graph.

If a live external API call is made (e.g. Stripe, SendGrid), the network firewall returns `ECONNREFUSED`. That appears in `stderr`, and the agent reads it to understand it needs to write a local mock.

```json
// Request
{
    "jsonrpc": "2.0",
    "method": "smp/sandbox/execute",
    "params": {
        "sandbox_id": "box_99x",
        "command":    "npm run test:local",
        "timeout_ms": 30000
    },
    "id": 102
}

// Response — tests pass, eBPF discovered new runtime edges
{
    "jsonrpc": "2.0",
    "result": {
        "exit_code": 0,
        "stdout":    "12 tests passed",
        "stderr":    "",
        "duration_ms": 4200,
        "calls_runtime_injected": [
            {
                "from": "func_process_payment",
                "to":   "func_handle_stripe_webhook",
                "call_count": 3
            }
        ]
    },
    "id": 102
}

// Response — live API hit, network blocked, stderr shows it
{
    "jsonrpc": "2.0",
    "result": {
        "exit_code": 1,
        "stdout":    "",
        "stderr":    "Error: connect ECONNREFUSED api.stripe.com:443",
        "duration_ms": 312,
        "calls_runtime_injected": [],
        "network_blocks": [
            {"host": "api.stripe.com", "port": 443, "reason": "egress_blocked"}
        ]
    },
    "id": 102
}
```

Agent reads `network_blocks`, writes a local Stripe mock, re-executes. No human needed.

---

#### smp/sandbox/destroy — Tear down sandbox and release resources

```json
// Request
{
    "jsonrpc": "2.0",
    "method": "smp/sandbox/destroy",
    "params": {
        "sandbox_id": "box_99x",
        "session_id": "ses_4f8a2c"
    },
    "id": 103
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "sandbox_id":   "box_99x",
        "status":       "destroyed",
        "destroyed_at": "2025-02-15T10:50:00Z",
        "resources_freed": {
            "filesystem_mb": 240,
            "services_stopped": ["postgres:15", "redis:7"]
        }
    },
    "id": 103
}
```

---

#### smp/verify/integrity — AST data-flow + mutation testing gate

The final gate before handoff. Two checks run in sequence:

**1. AST Data-Flow Check** — parses the test file's AST and confirms there is a data-flow edge from the tested function's *output* into a formal `assert()` / `expect()` call. Catches vacuous tests that call the function but assert nothing about its result.

**2. Mutation Testing** — deterministically flips operators in the source file (`<` → `>`, `===` → `!==`, `+1` → `-1`) and re-runs the test suite. If any mutant survives (tests still pass), the assertions are too loose. Gate rejects and returns the surviving mutant so the agent can tighten the test.

```json
// Request
{
    "jsonrpc": "2.0",
    "method": "smp/verify/integrity",
    "params": {
        "sandbox_id":  "box_99x",
        "target_file": "src/auth/login.ts",
        "test_file":   "tests/auth/login.test.ts"
    },
    "id": 104
}

// Response — passed both gates
{
    "jsonrpc": "2.0",
    "result": {
        "status":             "passed",
        "coverage_delta_pct": +14,
        "ast_assert_check":   "passed",
        "mutation_score":     1.0,
        "mutants_total":      8,
        "mutants_killed":     8,
        "mutants_survived":   0
    },
    "id": 104
}

// Response — surviving mutant detected
{
    "jsonrpc": "2.0",
    "result": {
        "status":           "failed",
        "failure_code":     "SURVIVING_MUTANT",
        "ast_assert_check": "passed",
        "mutation_score":   0.75,
        "mutants_total":    8,
        "mutants_killed":   6,
        "mutants_survived": 2,
        "survivors": [
            {
                "node_id":         "func_authenticate_user",
                "file":            "src/auth/login.ts",
                "line":            31,
                "original_op":     "===",
                "mutated_op":      "!==",
                "surviving_test":  "tests/auth/login.test.ts:44"
            }
        ]
    },
    "id": 104
}

// Response — no assert connected to function output
{
    "jsonrpc": "2.0",
    "result": {
        "status":           "failed",
        "failure_code":     "MISSING_AST_ASSERT",
        "ast_assert_check": "failed",
        "missing_assert_for": [
            {"node_id": "func_authenticate_user", "output_type": "Promise<Token>"}
        ]
    },
    "id": 104
}
```

---

## Part 7: Swarm Handoff

Once a coder agent passes `smp/verify/integrity`, it hands off to a reviewer agent or files a PR directly. The PR carries the full structural diff and execution log — not just code diffs.

---

#### smp/handoff/review — Pass sandbox to a reviewer agent

```json
// Request
{
    "jsonrpc": "2.0",
    "method": "smp/handoff/review",
    "params": {
        "sandbox_id":       "box_99x",
        "session_id":       "ses_4f8a2c",
        "reviewer_agent":   "reviewer_agent_02",
        "verify_result_id": "ver_8b2d1e"
    },
    "id": 105
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "handoff_id":        "hnd_7f3a9c",
        "reviewer_agent":    "reviewer_agent_02",
        "sandbox_id":        "box_99x",
        "status":            "pending_review",
        "reviewer_session":  "ses_rv_5d2f1a"
    },
    "id": 105
}
```

---

#### smp/handoff/pr — Package verified work as a Pull Request

Called after peer review passes, or directly if no reviewer agent is configured. Compiles the structural diff, runtime edges discovered, test results, and mutation score into a standard GitHub/GitLab PR payload.

```json
// Request
{
    "jsonrpc": "2.0",
    "method": "smp/handoff/pr",
    "params": {
        "sandbox_id":   "box_99x",
        "session_id":   "ses_4f8a2c",
        "base_sha":     "a1b2c3d4",
        "title":        "fix: rate limiting logic in auth module",
        "issue_refs":   ["#42"],
        "include": {
            "structural_diff":   true,
            "runtime_edges":     true,
            "mutation_score":    true,
            "execution_log":     true
        }
    },
    "id": 106
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "pr_id":        "pr_gh_1847",
        "status":       "open",
        "base_sha":     "a1b2c3d4",
        "head_sha":     "f9e3c2b1",
        "files_changed": ["src/auth/login.ts", "src/middleware/rateLimit.ts"],
        "structural_diff": {
            "nodes_added":            1,
            "nodes_modified":         1,
            "signature_changed":      false,
            "calls_runtime_added":    1
        },
        "test_summary": {
            "coverage_delta_pct":  +14,
            "mutation_score":       1.0
        }
    },
    "id": 106
}
```

---

#### Swarm Notifications (Server → Agent)

```json
// Sandbox network block — live API call attempted and blocked
{
    "jsonrpc": "2.0",
    "method": "smp/notification",
    "params": {
        "type":         "network_blocked",
        "severity":     "info",
        "sandbox_id":   "box_99x",
        "blocked_host": "api.stripe.com",
        "blocked_port": 443
    }
}
```

```json
// Handoff ready — reviewer agent has accepted the sandbox
{
    "jsonrpc": "2.0",
    "method": "smp/notification",
    "params": {
        "type":            "handoff_accepted",
        "severity":        "info",
        "handoff_id":      "hnd_7f3a9c",
        "reviewer_agent":  "reviewer_agent_02",
        "sandbox_id":      "box_99x"
    }
}
```

---

## Part 8: Implementation Stack

### Recommended Technologies

| Component | Technology | Why |
|-----------|------------|-----|
| **Parser** | Tree-sitter | Multi-language structural parsing (functions, classes, interfaces, calls) |
| **Graph store** | mmap journal (`.smpg`) | Self-contained nodes/edges/sessions/telemetry; in-process keyword search |
| **Vector store** | FAISS over mmap (`.smpv`) | Bring-your-own-embeddings via `smp/vector/*`; ingest creates none |
| **Merkle Index** | SHA-256 tree (built in-process) | O(log n) incremental sync — no full re-index; enables secure index distribution |
| **Sandbox Runtime** | Docker / Firecracker microVMs | Ephemeral, CoW filesystem, hard egress firewall |
| **Container Topology** | Testcontainers | Spin up local Postgres, Redis, etc. per sandbox |
| **Runtime Tracing** | eBPF daemon (BCC / libbpf) | Kernel-level call capture — zero app instrumentation needed |
| **Mutation Testing** | Stryker (JS/TS) / mutmut (Python) | Deterministic, no LLM, kills tautological tests |
| **Data Models** | msgspec | Zero-copy, schema-validated structs for internal data flow |
| **Protocol** | JSON-RPC 2.0 | Standard, simple, MCP-compatible |
| **Language** | Python (prototype) → Rust (production) | Start fast, optimize later |

---

### File Structure

The protocol router uses a **method map** — each method group lives in its own handler module under
`smp/protocol/handlers/`, registered by name in `smp/protocol/server.py`. No god-file `if/elif` chain.

```
smp/
├── store/graph/
│   ├── parser.py            # AST extraction (Tree-sitter, 14 languages)
│   ├── mmap_store.py        # mmap journal graph store + resolve_placeholders
│   ├── query.py             # Keyword search over names/docstrings/tags/paths
│   └── manifest.py          # File manifest
│   ├── engine/
│   │   ├── graph_builder.py # Build structural graph
│   │   └── query.py         # DefaultQueryEngine: navigate/trace/context/impact/locate/flow
│   ├── vector/
│   │   ├── faiss_index.py   # FAISS HNSW wrapper (cosine similarity)
│   │   └── mmap_vector.py   # mmap-backed BYO-embeddings store
│   ├── protocol/
│   │   └── handlers/
│   │       ├── memory.py        # smp/update, batch_update, sync, merkle/tree
│   │       ├── index.py         # smp/index/export, import
│   │       ├── community.py     # smp/community/detect (connected components), list, get
│   │       ├── query.py         # smp/navigate, trace, context, impact, locate, flow, diff, why
│   │       ├── enrichment.py    # smp/enrich, annotate, tag, search
│   │       ├── vector.py        # smp/vector/search, upsert, delete (caller-supplied embeddings)
│   │       ├── safety.py        # smp/session/*, guard/check, dryrun, checkpoint, lock, audit
│   │       ├── planning.py      # smp/plan, conflict
│   │       ├── sandbox.py       # smp/sandbox/spawn, execute, destroy
│   │       ├── verify.py        # smp/verify/integrity
│   │       ├── handoff.py       # smp/handoff/review, pr
│   │       └── telemetry.py     # smp/telemetry/*
│   └── main.py                  # Server entry point + full-text index init
├── clients/
│   ├── python_client.py         # Python SDK for agents
│   ├── typescript_client.ts     # TS SDK for agents
│   └── cli.py                   # Manual interaction
├── watchers/
│   ├── file_watcher.py          # Watch for file changes
│   └── git_hook.py              # Git-based updates
└── tests/
    └── ...
```

**Method map pattern** (`smp/protocol/server.py` maps names to plain async handlers):

```python
# smp/protocol/server.py
_HANDLERS = {
    "smp/navigate": query_handlers.navigate,
    "smp/trace": query_handlers.trace,
    "smp/locate": query_handlers.locate,
    "smp/search": query_handlers.search,
    # ... ~50 smp/* methods
}
```

```python
# smp/protocol/handlers/query.py
async def navigate(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle smp/navigate."""
    p = msgspec.convert(params, NavigateParams)
    engine = ctx["engine"]
    return await engine.navigate(p.query, p.include_relationships)

async def trace(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Handle smp/trace."""
    p = msgspec.convert(params, TraceParams)
    engine = ctx["engine"]
    result = await engine.trace(p.start, p.relationship, p.depth, p.direction)
    return {"nodes": result}
```

---

## Part 9: Agent Integration Example

### Agent Workflow with SMP

```python
class CodingAgent:
    def __init__(self, smp_client):
        self.smp = smp_client
    
    def edit_file(self, file_path, instruction):
        # 1. Open a session — declare scope upfront
        session = self.smp.call("smp/session/open", {
            "agent_id": self.agent_id,
            "task": instruction,
            "scope": [file_path],
            "mode": "write"
        })

        # 2. Pre-flight guard check
        guard = self.smp.call("smp/guard/check", {
            "session_id": session["session_id"],
            "target": file_path
        })
        if guard["verdict"] == "blocked":
            raise AbortError(guard["reasons"])

        # 3. Get full structural context
        context = self.smp.call("smp/context", {
            "file_path": file_path,
            "scope": "edit"
        })

        # 4. Dry run the proposed change
        dryrun = self.smp.call("smp/dryrun", {
            "session_id": session["session_id"],
            "file_path": file_path,
            "proposed_content": new_code,
        })
        if dryrun["verdict"] == "breaking":
            raise AbortError(dryrun["risks"])

        # 5. Checkpoint, write, sync memory
        self.smp.call("smp/checkpoint", {"session_id": session["session_id"], "files": [file_path]})
        write_to_disk(file_path, new_code)
        self.smp.call("smp/update", {"file_path": file_path, "content": new_code, "change_type": "modified"})

        # 6. Close session
        self.smp.call("smp/session/close", {"session_id": session["session_id"], "status": "completed"})
```

---

## Summary

| Component | Purpose |
|-----------|---------|
| **Parser** | Extract AST from code (Tree-sitter, 14 languages) |
| **Graph Builder** | Create structural relationships |
| **Linker** | Same-file call resolution at ingest + global `resolve_placeholders` (over-approximates) |
| **Enricher** | Attach static metadata — docstrings, annotations, tags (no LLM, no embeddings) |
| **Graph store** | mmap journal (`.smpg`) — self-contained structure, sessions, telemetry; keyword search in-process |
| **Vector store** | FAISS over mmap (`.smpv`) — bring-your-own-embeddings via `smp/vector/*`; ingest creates none |
| **Merkle Index** | SHA-256 tree over all file nodes — O(log n) incremental sync, powers `smp/sync` + secure index distribution |
| **Query Engine** | Keyword search (locate/search) + walks: navigate, trace, context, impact, flow, diff, plan, why |
| **SMP Protocol** | JSON-RPC 2.0 via method map (`_HANDLERS`) — handlers split by domain, no god file |
| **Agent Safety** | Sessions (persisted, MVCC or exclusive), guard checks, dry runs, checkpoints, audit log |
| **Telemetry** | Hot node tracking, heat scores, automatic safety escalation |
| **Community Detection** | Connected components (coarse + fine) — overviews + `smp/community/boundaries` coupling |
| **Sandbox Runtime** | Ephemeral microVM/Docker, CoW filesystem, hard egress firewall, eBPF trace capture |
| **Integrity Gate** | AST data-flow check + deterministic mutation testing — anti-gamification, no LLM |
| **Swarm Handoff** | Peer review pass-off + structured PR with structural diff, runtime edges, mutation score |

---

