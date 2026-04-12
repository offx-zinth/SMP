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
│                     │  ┌─────────────┐  ┌──────────────┐   │    │
│                     │  │ GRAPH DB    │  │ VECTOR STORE │   │    │
│                     │  │ (Structure) │  │ (Purpose)    │   │    │
│                     │  └─────────────┘  └──────────────┘   │    │
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

**Purpose:** Add meaning to structural nodes.

**Process:**

1. **Static Analysis (No LLM needed):**
   - Extract docstrings
   - Parse comments
   - Infer from naming conventions (`getUserById` → "retrieves user by identifier")
   - Extract type information

2. **LLM Enrichment (One-time per node):**
   ```
   Prompt: "In 1 sentence, what is the PURPOSE of this code in the system?"
   
   Input:
   - Function signature
   - Docstring
   - Dependencies
   - Called-by relationships
   
   Output:
   "Handles user authentication by validating credentials against the database 
   and issuing JWT tokens for session management."
   ```

3. **Embedding Generation:**
   - Embed the purpose + signature + key context
   - Store in vector database for similarity search

**Enriched Node:**

```json
{
    "id": "func_authenticate_user",
    "structural": { ... },
    "semantic": {
        "purpose": "Handles user authentication by validating credentials against the database and issuing JWT tokens for session management",
        "keywords": ["auth", "login", "jwt", "credentials", "validation"],
        "embedding": [0.123, -0.456, ...],
        "last_enriched": "2025-02-15T10:30:00Z",
        "confidence": 0.92
    }
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
| **Graph DB** | Neo4j / Memgraph / SQLite (if lightweight) | Native graph queries |
| **Vector Store** | Chroma / Qdrant / LanceDB | Semantic search |
| **Embedding** | OpenAI text-embedding-3-small | Good balance of speed/quality |
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

