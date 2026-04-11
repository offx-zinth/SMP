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
│  ┌──────────────────────────────────────────▼───────────────┐   │
│  │                    MEMORY STORE (Graph DB)               │   │
│  │  Structure · CALLS_STATIC · CALLS_RUNTIME · Sessions ·   │   │
│  │  Sandboxes · Audit Log · Telemetry · Full-Text (BM25)    │   │
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
│  Telemetry      │   │  eBPF trace capture  │   │               │
└────────┬────────┘   │  Egress-firewalled   │   └───────┬───────┘
         │            └──────────┬───────────┘           │
         └──────────────┬────────┘───────────────────────┘
                        │                       
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
└─────────────────────────────────────────────────────────────┘
```

**Example Graph Node:**

```json
{
    "id": "func_authenticate_user",
    "type": "Function",
    "name": "authenticateUser",
    "file": "src/auth/login.ts",
    "signature": "authenticateUser(email: string, password: string): Promise<Token>",
    "metrics": {
        "complexity": 4,
        "lines": 28,
        "parameters": 2
    },
    "relationships": {
        "CALLS": ["func_hashPassword", "func_compareHash", "func_generateToken"],
        "DEPENDS_ON": ["class_UserModel"],
        "DEFINED_IN": "file_auth_login_ts"
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

#### smp/search — Full-text search across enriched metadata

BM25-ranked full-text search against docstrings, descriptions, and tags. Backed by a Neo4j Full-Text Index — no table scans, no `CONTAINS` on raw strings. Scales to 100k+ nodes.

**Index configuration (one-time setup at server start):**

```cypher
-- Create the full-text index covering all enrichable node types
CALL db.index.fulltext.createNodeIndex(
  "smp_fulltext",
  ["Function", "Class", "Interface", "Variable"],
  ["semantic_docstring", "semantic_description", "semantic_tags"]
)
```

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

// Response — results ranked by BM25 score (term frequency + inverse doc frequency)
{
    "jsonrpc": "2.0",
    "result": {
        "matches": [
            {
                "node_id": "func_xT9_handler",
                "node_type": "Function",
                "file": "src/payments/webhook.ts",
                "docstring": "Processes Stripe webhook payload and updates subscription status in DB.",
                "tags": ["billing", "webhook", "stripe"],
                "matched_on": ["docstring", "tags"],
                "bm25_score": 4.72
            },
            {
                "node_id": "class_StripeClient",
                "node_type": "Class",
                "file": "src/payments/stripe.ts",
                "docstring": "Thin wrapper around the Stripe SDK for payment operations.",
                "tags": ["billing", "stripe"],
                "matched_on": ["docstring", "tags"],
                "bm25_score": 3.18
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
        "searched_fields": ["docstring", "tags"],
        "scope_node_count": 312
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
        "status": "enriched",          // "enriched" | "manually_annotated" | "no_metadata"
        "docstring": "Validates user credentials and returns a signed JWT for the session.",
        "description": null,           // set only if manually annotated via smp/annotate
        "drift_suspected": true,    // AST complexity changed by >20% but docstring hash is identical
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

---

## Part 2: The Query Engine

> **Token Optimization (LLM UX):** All Query Engine endpoints (`smp/context`, `smp/flow`, `smp/navigate`) support an `accept: "text/markdown"` header. Instead of raw JSON, the server compiles the graph data into a dense, token-optimized Markdown briefing designed specifically for LLM ingestion, preventing context-window exhaustion.

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
class StructuralQueryEngine:
    def __init__(self, graph_db):
        self.graph = graph_db
    
    def navigate(self, entity_name: str, direction: str = "to"):
        """Find entity and its relationships"""
        pass
    
    def trace(self, start_id: str, relationship_type: str, depth: int = 3):
        """Follow relationship chain"""
        pass
    
    def get_context(self, file_path: str, scope: str = "edit"):
        """
        Proactive context gathering.
        
        scope options:
        - "edit": What do I need to edit this file safely?
        - "create": What pattern should I follow for new file?
        - "debug": What's the data flow through this file?
        """
        pass
    
    def assess_impact(self, entity_id: str, change_type: str):
        """What would break if I change/delete this?"""
        pass
    
    def locate(self, query: str):
        """Find code by keyword match against names, docstrings, and tags"""
        pass
    
    def trace_flow(self, start: str, end: str = None):
        """Trace execution/data flow"""
        pass
```

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
// smp/reindex - Full re-index (for major refactors)
{
    "jsonrpc": "2.0",
    "method": "smp/reindex",
    "params": {
        "scope": "full" | "package:src/auth"
    },
    "id": 3
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
            "risk_level": "high",
            "required_services": ["postgres:15", "redis:7"]
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

#### 4. Keyword Search

```json
// smp/locate - Find nodes by BM25-ranked keyword search against names, docstrings, and tags.
// Backed by the same Neo4j Full-Text Index as smp/search.
// Ranking order: exact name match → name substring → BM25 score on docstring/tags.
{
    "jsonrpc": "2.0",
    "method": "smp/locate",
    "params": {
        "query": "user registration",
        "fields": ["name", "docstring", "tags"],
        "node_types": ["Function", "Class"],
        "top_k": 5
    },
    "id": 8
}

// Response — ranked by match tier then BM25 score within tier
{
    "jsonrpc": "2.0",
    "result": {
        "matches": [
            {
                "entity": "func_register_user",
                "file": "src/auth/register.ts",
                "matched_on": "name",
                "docstring": "Creates a new user account and sends verification email.",
                "tags": ["auth", "registration"],
                "bm25_score": 6.10
            },
            {
                "entity": "class_UserService",
                "file": "src/services/user.ts",
                "matched_on": "docstring",
                "docstring": "Manages user CRUD operations including registration and deletion.",
                "tags": ["user", "service"],
                "bm25_score": 3.84
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
        },
        "human_risk_briefing": {
            "level": "High",
            "summary": "Agent modified `authenticateUser` (a Hot Node with 12 callers). Structural diff shows signature is unchanged. eBPF runtime trace confirmed tests covered all new branches. Mutation score is 1.0 (no gamification detected). Safe to merge.",
            "requires_manual_review": ["src/middleware/rateLimit.ts - Network egress attempted to Redis"]
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
| **Parser** | Tree-sitter | Multi-language, incremental, fast |
| **Graph DB** | Neo4j / Memgraph | Native graph queries, BM25 full-text index, persists sessions + telemetry + CALLS_RUNTIME |
| **Graph DB (lightweight)** | SQLite + recursive CTEs | Single-machine or embedded use |
| **Sandbox Runtime** | Docker / Firecracker microVMs | Ephemeral, CoW filesystem, hard egress firewall |
| **Container Topology** | Testcontainers | Spin up local Postgres, Redis, etc. per sandbox |
| **Runtime Tracing** | eBPF daemon (BCC / libbpf) | Kernel-level call capture — zero app instrumentation needed |
| **Mutation Testing** | Stryker (JS/TS) / mutmut (Python) | Deterministic, no LLM, kills tautological tests |
| **Protocol** | JSON-RPC 2.0 | Standard, simple, MCP-compatible |
| **Language** | Python (prototype) → Rust (production) | Start fast, optimize later |

---

### File Structure

The protocol router uses a **Dispatcher Pattern** — each method group lives in its own handler module with a `@rpc_method` decorator. No god-file `if/elif` chain.

```
structural-memory/
├── server/
│   ├── core/
│   │   ├── parser.py            # AST extraction (Tree-sitter)
│   │   ├── graph_builder.py     # Build structural graph
│   │   ├── linker.py            # Static namespaced CALLS resolution
│   │   ├── linker_runtime.py    # eBPF trace ingestion → CALLS_RUNTIME edges
│   │   ├── enricher.py          # Static metadata extraction
│   │   ├── telemetry.py         # Hot node tracking + heat scores
│   │   └── store.py             # Graph DB interface + full-text index setup
│   ├── engine/
│   │   ├── navigator.py         # Graph traversal (navigate, trace, flow, why)
│   │   ├── reasoner.py          # Proactive context + summary computation
│   │   └── guard.py             # Guard checks, dry run, test-gap analysis
│   ├── sandbox/
│   │   ├── spawner.py           # Docker / Firecracker microVM lifecycle
│   │   ├── executor.py          # Command runner + stdout/stderr capture
│   │   ├── ebpf_collector.py    # eBPF daemon interface + trace → graph edges
│   │   ├── network_policy.py    # Egress firewall rules + block notifications
│   │   └── verifier.py          # AST data-flow check + mutation test runner
│   ├── protocol/
│   │   ├── dispatcher.py        # @rpc_method decorator + method registry
│   │   └── handlers/
│   │       ├── memory.py        # smp/update, batch_update, reindex
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
│   ├── typescript_client.ts     # TS SDK for agents
│   └── cli.py                   # Manual interaction
├── watchers/
│   ├── file_watcher.py          # Watch for file changes
│   └── git_hook.py              # Git-based updates
└── tests/
    └── ...
```

**Dispatcher pattern:**

```python
# protocol/dispatcher.py
_registry: dict[str, Callable] = {}

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
```

```python
# protocol/handlers/query.py
from protocol.dispatcher import rpc_method

@rpc_method("smp/navigate")
def handle_navigate(params, ctx):
    return ctx.engine.navigator.navigate(params["query"], params.get("include_relationships", False))

@rpc_method("smp/trace")
def handle_trace(params, ctx):
    return ctx.engine.navigator.trace(params["start"], params["relationship"], params.get("depth", 3))
```

---

## Part 9: Agent Integration Example

### Agent Workflow with SMP (Sandbox + MVCC)

```python
class AutonomousCodingAgent:
    def __init__(self, smp_client):
        self.smp = smp_client
    
    def complete_task(self, file_path, instruction):
        # 1. Open an MVCC session against the current branch head
        session = self.smp.call("smp/session/open", {
            "agent_id": self.agent_id,
            "task": instruction,
            "scope": [file_path],
            "mode": "write",
            "concurrency": "mvcc"
        })
        session_id = session["session_id"]

        # 2. Get structural context & required services
        context = self.smp.call("smp/context", {"file_path": file_path, "scope": "edit"})
        services = context["summary"].get("required_services", [])

        # 3. Spawn isolated Sandbox with Testcontainers
        sandbox = self.smp.call("smp/sandbox/spawn", {
            "session_id": session_id,
            "image": "node:20-alpine",
            "services": services,
            "inject_ebpf": True
        })
        box_id = sandbox["sandbox_id"]

        # 4. Agent writes code (LLM generation happens here)
        new_code = self._generate_code(instruction, context)
        test_code = self._generate_tests(instruction, context)

        # 5. Sync edits to the Memory Server AND Sandbox CoW filesystem
        self.smp.call("smp/update", {"file_path": file_path, "content": new_code})
        self.smp.call("smp/update", {"file_path": f"tests/{file_path}", "content": test_code})

        # 6. Execution & Self-Correction Loop
        max_retries = 3
        for attempt in range(max_retries):
            exec_result = self.smp.call("smp/sandbox/execute", {
                "sandbox_id": box_id,
                "command": "npm run test:local"
            })
            
            if exec_result["exit_code"] == 0:
                break # Tests passed!
                
            if "network_blocks" in exec_result:
                # Agent self-corrects: writes a local mock for the blocked API
                self._mock_external_dependency(exec_result["network_blocks"])
            else:
                # Agent self-corrects based on stderr
                self._fix_code_based_on_stderr(exec_result["stderr"])

        # 7. Final Integrity Verification (AST Data-flow + Mutation)
        verify = self.smp.call("smp/verify/integrity", {
            "sandbox_id": box_id,
            "target_file": file_path,
            "test_file": f"tests/{file_path}"
        })

        if verify["status"] == "failed":
            if verify["failure_code"] == "SURVIVING_MUTANT":
                self._tighten_assertions(verify["survivors"])
            raise AbortError("Failed to satisfy integrity gate.")

        # 8. Handoff: Package verified sandbox into a Pull Request
        self.smp.call("smp/handoff/pr", {
            "sandbox_id": box_id,
            "session_id": session_id,
            "title": f"Agent auto-fix: {instruction}",
            "include": {"structural_diff": True, "runtime_edges": True}
        })
        
        # 9. Clean up
        self.smp.call("smp/session/close", {"session_id": session_id, "status": "completed"})
```

---

## Summary

| Component | Purpose |
|-----------|---------|
| **Parser** | Extract AST from code (Tree-sitter) |
| **Graph Builder** | Create structural relationships |
| **Static Linker** | Namespace-aware cross-file CALLS resolution — no ambiguous edges |
| **Runtime Linker** | eBPF execution traces → `CALLS_RUNTIME` edges — resolves DI and metaprogramming |
| **Enricher** | Attach static metadata — docstrings, annotations, tags |
| **Memory Store** | Graph DB — structure, `CALLS_STATIC`, `CALLS_RUNTIME`, sessions, telemetry, BM25 index |
| **Query Engine** | navigate, trace, context (+summary), impact, locate, flow, diff, plan, conflict, why |
| **SMP Protocol** | JSON-RPC 2.0 via Dispatcher — handlers split by domain, no god file |
| **Agent Safety** | Sessions (persisted, MVCC or exclusive), guard checks, dry runs, checkpoints, audit log |
| **Telemetry** | Hot node tracking, heat scores, automatic safety escalation |
| **Sandbox Runtime** | Ephemeral microVM/Docker, CoW filesystem, hard egress firewall, eBPF trace capture |
| **Integrity Gate** | AST data-flow check + deterministic mutation testing — anti-gamification, no LLM |
| **Swarm Handoff** | Peer review pass-off + structured PR with structural diff, runtime edges, mutation score |

---

