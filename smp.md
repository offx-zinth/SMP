# The Structural Memory Protocol (SMP)

A framework for giving AI agents a "programmer's brain" — not text retrieval, but structural understanding.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     CODEBASE (Files)                            │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Updates (Watch / Agent Push)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   MEMORY SERVER (SMP Core)                      │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐            │
│  │   PARSER    │─▶│ GRAPH BUILDER│──▶│  ENRICHER   │            │
│  │ (AST/Tree-  │   │ (Structural │   │ (Semantic   │            │
│  │  sitter)    │   │  Analysis)  │   │  Layer)     │            │
│  └─────────────┘   └─────────────┘   └──────┬──────┘            │
│                                             │                   │
│                     ┌───────────────────────▼──────────────┐    │
│                     │         MEMORY STORE                 │    │
│                     │       ┌─────────────┐                 │    │
│                     │       │ GRAPH DB    │                 │    │
│                     │       │ (Structure  │                 │    │
│                     │       │  + Tags)    │                 │    │
│                     │       └─────────────┘                 │    │
│                     └───────────────────────┬──────────────┘    │
└─────────────────────────────────────────────┼──────────────────-┘
                                              │
                    ┌─────────────────────────▼──────────────────┐
                    │         QUERY ENGINE (SMP Interface)       │
                    │  ┌────────────┐  ┌────────────┐            │
                    │  │ Navigator  │  │ Reasoner   │            │
                    │  │ (Graph     │  │ (Proactive │            │
                    │  │  Traversal)│  │  Context)  │            │
                    │  └────────────┘  └────────────┘            │
                    └───────────────────────┬────────────────────┘
                                            │ SMP Protocol
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
│  CALLS         │ Function calls Function                    │
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

### C. Semantic Enricher

**Purpose:** Tag every node with queryable labels derived purely from static analysis — no LLM, no embeddings, no ML of any kind. Everything here is deterministic and computable at parse time.

---

#### What Gets Attached to Each Node

Four purely-computable fields that make graph queries expressive:

```
intent      →  what the node is trying to do        (from name + docstring)
category    →  what domain bucket it belongs to      (from name patterns + file path)
tags        →  flat set of searchable labels          (from all sources below)
role        →  structural role in the architecture   (from graph shape)
```

These become **filterable graph node properties** — agents query them directly, no similarity search needed.

---

#### Source 1 — Verb Prefix → Intent

Split the function name at camelCase/snake_case boundaries. The first token (verb) maps to a known intent.

```python
VERB_INTENT = {
    "get":          "read",      "fetch":      "read",
    "find":         "read",      "list":       "read",
    "load":         "read",      "read":       "read",
    "query":        "read",      "search":     "read",

    "set":          "write",     "save":       "write",
    "update":       "write",     "upsert":     "write",
    "write":        "write",     "persist":    "write",
    "patch":        "write",     "store":      "write",

    "create":       "create",    "build":      "create",
    "make":         "create",    "generate":   "create",
    "new":          "create",    "init":       "create",
    "construct":    "create",    "spawn":      "create",

    "delete":       "delete",    "remove":     "delete",
    "destroy":      "delete",    "drop":       "delete",
    "purge":        "delete",    "clear":      "delete",

    "validate":     "validate",  "check":      "validate",
    "verify":       "validate",  "assert":     "validate",
    "ensure":       "validate",  "is":         "validate",
    "has":          "validate",  "can":        "validate",

    "parse":        "transform", "convert":    "transform",
    "map":          "transform", "transform":  "transform",
    "format":       "transform", "serialize":  "transform",
    "deserialize":  "transform", "decode":     "transform",

    "send":         "io",        "emit":       "io",
    "publish":      "io",        "notify":     "io",
    "broadcast":    "io",        "dispatch":   "io",
    "render":       "io",        "print":      "io",

    "handle":       "handler",   "process":    "handler",
    "execute":      "handler",   "run":        "handler",

    "authenticate": "auth",      "authorize":  "auth",
    "login":        "auth",      "logout":     "auth",
    "permit":       "auth",      "guard":      "auth",
}

def extract_intent(name: str) -> str:
    verb = split_tokens(name)[0].lower()   # "authenticateUser" → "authenticate"
    return VERB_INTENT.get(verb, "unknown")
```

---

#### Source 2 — File Path → Category

The directory tree is the richest free signal in any codebase. No inference needed — the dev already categorized the code by where they put it.

```python
PATH_CATEGORY = [
    (r"auth|login|session|oauth|jwt|token",  "authentication"),
    (r"user|account|profile|member",         "user_management"),
    (r"payment|billing|invoice|stripe",      "payments"),
    (r"email|mail|smtp|notification|push",   "notifications"),
    (r"db|database|model|schema|migration",  "persistence"),
    (r"api|route|endpoint|controller|handler","api_layer"),
    (r"service|svc",                         "service_layer"),
    (r"util|helper|lib|common|shared",       "utilities"),
    (r"middleware|interceptor|guard|filter",  "middleware"),
    (r"test|spec|__tests__",                 "tests"),
    (r"config|env|settings",                 "configuration"),
    (r"cache|redis|memcache",                "caching"),
    (r"queue|job|worker|task|cron",          "background_jobs"),
    (r"event|bus|pubsub|stream",             "event_system"),
    (r"types|interfaces|models|dto",         "type_definitions"),
]

def extract_category(file_path: str) -> str:
    for pattern, category in PATH_CATEGORY:
        if re.search(pattern, file_path, re.IGNORECASE):
            return category
    return "uncategorized"
```

---

#### Source 3 — Graph Shape → Role

A node's position and connectivity in the graph reveals its architectural role, with zero ML.

```python
def extract_role(node: GraphNode, graph: Graph) -> str:
    in_deg  = graph.in_degree(node)   # how many things call this
    out_deg = graph.out_degree(node)  # how many things this calls
    is_exported = "export" in node.modifiers
    is_tested   = graph.has_relationship(node, "TESTS", direction="incoming")

    if in_deg == 0 and is_exported:
        return "public_api"        # entry point, called from outside

    if in_deg > 10:
        return "utility"           # everyone depends on it → shared helper

    if out_deg == 0:
        return "leaf"              # calls nothing → pure computation or I/O

    if out_deg > 8:
        return "orchestrator"      # fans out to many things → coordinator

    if in_deg > 5 and out_deg > 5:
        return "hub"               # high traffic both ways → core logic

    if is_tested and in_deg <= 2:
        return "testable_unit"     # small, tested, isolated

    return "internal"
```

---

#### Source 4 — Keyword Tags

A flat, queryable tag set merged from all sources above. Agents can filter on these directly.

```python
def build_tags(node, intent, category, role, docstring) -> set[str]:
    tags = set()

    tags.add(intent)       # "read", "write", "auth", ...
    tags.add(category)     # "authentication", "payments", ...
    tags.add(role)         # "orchestrator", "leaf", "public_api", ...
    tags.add(node.type)    # "function", "class", "interface", ...

    # async / sync
    if "async" in node.modifiers or "Promise" in (node.return_type or ""):
        tags.add("async")
    else:
        tags.add("sync")

    # exported / internal
    tags.add("exported" if "export" in node.modifiers else "internal")

    # has tests?
    tags.add("tested" if graph.has_relationship(node, "TESTS", "incoming") else "untested")

    # return type signals
    if node.return_type in ("void", "None", "unit"):
        tags.add("side_effect")
    else:
        tags.add("pure_output")

    # keyword tokens from docstring (no NLP — just split + stopword filter)
    if docstring:
        tokens = tokenize(docstring)                     # split on whitespace/punct
        tags |= {t for t in tokens if t not in STOPWORDS and len(t) > 3}

    return tags
```

---

#### Final Enriched Node

```json
{
    "id": "func_authenticate_user",
    "structural": {
        "signature": "authenticateUser(email: string, password: string): Promise<Token>",
        "file": "src/auth/login.ts",
        "lines": 28,
        "complexity": 4
    },
    "semantic": {
        "intent":   "auth",
        "category": "authentication",
        "role":     "public_api",
        "tags":     ["auth", "authentication", "public_api", "function", "async", "exported", "tested", "pure_output", "credentials", "jwt", "session"],
        "enriched_at": "2025-02-15T10:30:00Z"
    }
}
```

---

#### What This Enables (Pure Graph Queries)

```python
# "Show me all untested public API functions in the auth layer"
graph.query("""
    MATCH (f:Function)
    WHERE f.semantic.category = 'authentication'
      AND f.semantic.role = 'public_api'
      AND 'untested' IN f.semantic.tags
    RETURN f
""")

# "What are all the orchestrators in the payments module?"
graph.query("""
    MATCH (f:Function)
    WHERE f.semantic.role = 'orchestrator'
      AND f.semantic.category = 'payments'
    RETURN f
""")

# "Find all side-effectful write operations"
graph.query("""
    MATCH (f:Function)
    WHERE f.semantic.intent = 'write'
      AND 'side_effect' IN f.semantic.tags
    RETURN f
""")
```

No vector search. No embeddings. No LLM. Just graph properties and filters.

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
class StructuralQueryEngine:
    def __init__(self, graph_db, vector_store):
        self.graph = graph_db
        self.vectors = vector_store
    
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
    
    def locate_by_intent(self, description: str):
        """Find code by what it does, not its name"""
        # Vector search on semantic embeddings
        # Return ranked structural matches
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
    Returns the "programmer's mental model" for a file.
    """
    file_node = self.graph.get_node_by_path(file_path)
    
    context = {
        "self": file_node,  # What is this file?
        
        "imports": self.graph.get_relationships(
            file_node, "IMPORTS", direction="outgoing"
        ),  # What does it depend on?
        
        "imported_by": self.graph.get_relationships(
            file_node, "IMPORTS", direction="incoming"
        ),  # Who depends on it?
        
        "defines": self.graph.get_relationships(
            file_node, "DEFINES", direction="outgoing"
        ),  # What's inside?
        
        "related_patterns": self.vectors.find_similar(
            file_node.semantic.embedding, top_k=5
        ),  # Similar files (pattern reference)
        
        "entry_points": self.graph.find_entry_points(file_node),
        
        "data_flow_in": self.trace_data_flow(file_node, direction="in"),
        
        "data_flow_out": self.trace_data_flow(file_node, direction="out"),
    }
    
    return context
```

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

// Response: Full context needed to edit this file safely
{
    "jsonrpc": "2.0",
    "result": {
        "self": {...},
        "imports": [...],
        "imported_by": [...],
        "functions_defined": [...],
        "classes_defined": [...],
        "tests": ["tests/auth.test.ts"],
        "patterns": ["src/api/users.ts (similar structure)"],
        "warnings": ["This file is imported by 12 other files"]
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
        "affected_functions": ["loginRoute", "test_authenticate_user"],
        "severity": "high",
        "recommendations": [
            "Update loginRoute in routes.ts to match new signature",
            "Update test cases in auth.test.ts"
        ]
    },
    "id": 7
}
```

---

#### 4. Semantic Search

```json
// smp/locate - Find by description
{
    "jsonrpc": "2.0",
    "method": "smp/locate",
    "params": {
        "description": "where is user registration handled",
        "top_k": 5
    },
    "id": 8
}

// Response
{
    "jsonrpc": "2.0",
    "result": {
        "matches": [
            {
                "entity": "func_register_user",
                "file": "src/auth/register.ts",
                "purpose": "Handles new user registration...",
                "relevance": 0.94
            },
            {
                "entity": "class_UserService",
                "file": "src/services/user.ts",
                "purpose": "Manages user CRUD operations...",
                "relevance": 0.87
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
            {"node": "api_route_login", "type": "endpoint"},
            {"node": "auth_middleware", "type": "middleware"},
            {"node": "authenticateUser", "type": "function"},
            {"node": "UserModel.findByEmail", "type": "method"},
            {"node": "generateToken", "type": "function"},
            {"node": "response_json", "type": "output"}
        ],
        "data_transformations": [
            "Request body → credentials object",
            "Credentials → validated user",
            "User → JWT token"
        ]
    },
    "id": 9
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

## Part 4: Implementation Stack

### Recommended Technologies

| Component | Technology | Why |
|-----------|------------|-----|
| **Parser** | Tree-sitter | Multi-language, incremental, fast |
| **Graph DB** | Neo4j / Memgraph / SQLite (if lightweight) | Native graph queries, stores tags as node properties |
| **Protocol** | JSON-RPC 2.0 | Standard, simple, MCP-compatible |
| **Language** | Python (prototype) → Rust (production) | Start fast, optimize later |

---

### File Structure

```
structural-memory/
├── server/
│   ├── core/
│   │   ├── parser.py          # AST extraction (Tree-sitter)
│   │   ├── graph_builder.py   # Build structural graph
│   │   ├── enricher.py        # Semantic enrichment
│   │   └── store.py           # Graph + Vector store interface
│   ├── engine/
│   │   ├── query.py           # Query processing
│   │   ├── navigator.py       # Graph traversal
│   │   └── reasoner.py        # Proactive context
│   ├── protocol/
│   │   ├── smp_handler.py     # JSON-RPC handler
│   │   └── methods.py         # SMP method implementations
│   └── main.py                # Server entry point
├── clients/
│   ├── python_client.py       # Python SDK for agents
│   ├── typescript_client.ts   # TS SDK for agents
│   └── cli.py                 # Manual interaction
├── watchers/
│   ├── file_watcher.py        # Watch for file changes
│   └── git_hook.py            # Git-based updates
└── tests/
    └── ...
```

---

## Part 5: Agent Integration Example

### Agent Workflow with SMP

```python
class CodingAgent:
    def __init__(self, smp_client):
        self.smp = smp_client
    
    def edit_file(self, file_path, instruction):
        # 1. Get structural context
        context = self.smp.call("smp/context", {
            "file_path": file_path,
            "scope": "edit"
        })
        
        # 2. Understand impact
        impact = self.smp.call("smp/impact", {
            "entity": context["self"]["id"],
            "change_type": "signature_change"
        })
        
        # 3. Make the edit (with context-aware prompt)
        new_code = self.llm.edit(
            current_code=context["self"]["content"],
            instruction=instruction,
            context=context,
            warnings=impact
        )
        
        # 4. Update memory
        self.smp.call("smp/update", {
            "file_path": file_path,
            "content": new_code,
            "change_type": "modified"
        })
        
        return new_code
```

---

## Summary

| Component | Purpose |
|-----------|---------|
| **Parser** | Extract AST from code (Tree-sitter) |
| **Graph Builder** | Create structural relationships |
| **Enricher** | Add semantic meaning to nodes |
| **Memory Store** | Graph DB + Vector Store |
| **Query Engine** | Navigate, trace, context, impact, locate, flow |
| **SMP Protocol** | JSON-RPC interface for agent communication |

---

