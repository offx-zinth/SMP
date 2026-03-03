# Structural Memory Protocol (SMP)

A framework for giving AI agents a "programmer's brain" — not text retrieval, but structural understanding.

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
│  │   PARSER    │─▶│ GRAPH BUILDER│──▶│  ENRICHER   │           │
│  │ (AST/Tree-  │   │ (Structural │   │ (Semantic   │            │
│  │  sitter)    │   │  Analysis)  │   │  Layer)     │            │
│  └─────────────┘   └─────────────┘   └──────┬──────┘            │
│                                             │                   │
│                     ┌───────────────────────▼──────────────┐    │
│                     │         MEMORY STORE                 │    │
│                     │  ┌─────────────┐  ┌──────────────┐  │     │
│                     │  │ GRAPH DB    │  │ VECTOR STORE │  │     │
│                     │  │ (Structure) │  │ (Purpose)    │  │     │
│                     │  └─────────────┘  └──────────────┘  │     │
│                     └───────────────────────┬──────────────┘    │
└─────────────────────────────────────────────┼──────────────────┘
                                              │
                    ┌─────────────────────────▼──────────────────┐
                    │         QUERY ENGINE (SMP Interface)       │
                    │  ┌────────────┐  ┌────────────┐           │
                    │  │ Navigator  │  │ Reasoner   │           │
                    │  │ (Graph     │  │ (Proactive │           │
                    │  │  Traversal)│  │  Context)  │           │
                    │  └────────────┘  └────────────┘           │
                    └───────────────────────┬───────────────────┘
                                            │ SMP Protocol
                                            ▼
                    ┌─────────────────────────────────────────────┐
                    │              AGENT LAYER                     │
                    │   Agent A       Agent B       Agent C       │
                    │   (Coder)       (Reviewer)    (Architect)   │
                    └─────────────────────────────────────────────┘
```

## Installation

```bash
# Install dependencies
npm install

# Run development server
npm run dev
```

## Quick Start

### 1. Initialize with Sample Code

```bash
curl http://localhost:3000/api/smp/init
```

### 2. Query for Entities

```bash
curl -X POST http://localhost:3000/api/smp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "smp/navigate",
    "params": {
      "entity_name": "authenticateUser",
      "include_relationships": true
    },
    "id": 1
  }'
```

## Query Types

| Type | Purpose | Example |
|------|---------|---------|
| **Navigate** | Find specific entities | "Where is `login` defined?" |
| **Trace** | Follow relationships | "What calls `authenticateUser`?" |
| **Context** | Get relevant context | "I'm editing `auth.ts`, what do I need to know?" |
| **Impact** | Assess change impact | "If I delete this, what breaks?" |
| **Locate** | Find by description | "Where is user registration handled?" |
| **Flow** | Trace data/logic path | "How does a request become a DB entry?" |

## API Reference

### Memory Management

#### smp/update
Index a file into memory.

```json
{
  "jsonrpc": "2.0",
  "method": "smp/update",
  "params": {
    "file_path": "src/auth/login.ts",
    "content": "...",
    "change_type": "modified"
  },
  "id": 1
}
```

#### smp/batch_update
Index multiple files at once.

```json
{
  "jsonrpc": "2.0",
  "method": "smp/batch_update",
  "params": {
    "changes": [
      {"file_path": "file1.ts", "content": "...", "change_type": "created"},
      {"file_path": "file2.ts", "content": "...", "change_type": "created"}
    ]
  },
  "id": 2
}
```

### Structural Queries

#### smp/navigate
Find entity and its relationships.

```json
{
  "jsonrpc": "2.0",
  "method": "smp/navigate",
  "params": {
    "entity_name": "authenticateUser",
    "include_relationships": true
  },
  "id": 3
}
```

#### smp/trace
Follow relationship chain.

```json
{
  "jsonrpc": "2.0",
  "method": "smp/trace",
  "params": {
    "start_id": "func_authenticate_user",
    "relationship_type": "CALLS",
    "depth": 3,
    "direction": "outgoing"
  },
  "id": 4
}
```

### Context Queries

#### smp/context
Get editing context for a file.

```json
{
  "jsonrpc": "2.0",
  "method": "smp/context",
  "params": {
    "file_path": "src/auth/login.ts",
    "scope": "edit"
  },
  "id": 5
}
```

#### smp/impact
Assess change impact.

```json
{
  "jsonrpc": "2.0",
  "method": "smp/impact",
  "params": {
    "entity": "func_authenticate_user",
    "change_type": "signature_change"
  },
  "id": 6
}
```

### Semantic Search

#### smp/locate
Find code by description.

```json
{
  "jsonrpc": "2.0",
  "method": "smp/locate",
  "params": {
    "description": "where is user registration handled",
    "top_k": 5
  },
  "id": 7
}
```

### Flow Analysis

#### smp/flow
Trace execution/data flow.

```json
{
  "jsonrpc": "2.0",
  "method": "smp/flow",
  "params": {
    "start": "api_route_login",
    "flow_type": "execution"
  },
  "id": 8
}
```

## TypeScript Client SDK

```typescript
import { createBrowserClient } from '@/lib/smp/client';

const client = createBrowserClient();

// Navigate
const result = await client.navigate({
  entity_name: 'authenticateUser',
  include_relationships: true
});

// Locate by description
const matches = await client.locate({
  description: 'user authentication',
  top_k: 5
});

// Get context for editing
const context = await client.context({
  file_path: 'src/auth/login.ts',
  scope: 'edit'
});

// Assess impact
const impact = await client.impact({
  entity_id: 'func_authenticate_user',
  change_type: 'delete'
});
```

## Node Types

| Type | Description |
|------|-------------|
| Repository | Root node |
| Package | Directory/module |
| File | Source file |
| Class | Class definition |
| Function | Function/method |
| Variable | Variable/constant |
| Interface | Type definition/interface |
| Test | Test file/function |
| Config | Configuration file |

## Relationship Types

| Type | Description |
|------|-------------|
| CONTAINS | Parent-child (Package → File) |
| IMPORTS | File imports File/Module |
| DEFINES | File defines Class/Function |
| CALLS | Function calls Function |
| INHERITS | Class inherits Class |
| IMPLEMENTS | Class implements Interface |
| DEPENDS_ON | General dependency |
| TESTS | Test tests Function/Class |
| USES | Function uses Variable/Type |

## File Structure

```
src/lib/smp/
├── types.ts           # TypeScript interfaces
├── index.ts           # Main exports
├── core/
│   ├── parser.ts      # AST extraction
│   ├── graph-builder.ts  # Build structural graph
│   ├── enricher.ts    # Semantic enrichment
│   └── store.ts       # Graph + Vector store
├── engine/
│   └── query.ts       # Query processing
├── protocol/
│   └── handler.ts     # JSON-RPC handler
└── client.ts          # TypeScript SDK
```

## License

MIT
