# SMP Graph Engine - Technical Specification

## Overview

SMP Graph Engine is an **ingest-free, memory-mapped graph database** for code analysis at scale (10M+ LOC). It replaces Neo4j with a custom single-file storage format optimized for sparse access patterns and on-demand parsing.

### Key Properties

| Property | Value |
|----------|-------|
| **Storage** | Single `.smpg` file + optional `.smpv` for vectors |
| **Format** | Append-only, memory-mapped |
| **Scale** | 50M+ LOC, ~100GB disk, ~15GB RAM hot set |
| **Latency** | Index lookup <1ms, first-parse on-demand |
| **Crash Safety** | WAL (Write-Ahead Log) with replay |
| **Concurrency** | Lock-free reads, WAL-based writes |

---

## File Format

### `.smpg` Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ Offset 0..4095: HEADER (4096 bytes fixed)                      │
├─────────────────────────────────────────────────────────────────┤
│ Offset 4096..65535: WAL (64KB, configurable)                    │
│   - Circular buffer of 512-byte WAL records                     │
│   - Each record: {type, size, payload, crc32}                  │
│   - Commit records mark transaction boundaries                  │
├─────────────────────────────────────────────────────────────────┤
│ Offset 65536..: DATA REGION (sparse, grows as needed)           │
│                                                                  │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │ Crit-bit Index Pages                                    │   │
│   │   Key: node_id (64-bit hash)                           │   │
│   │   Value: InodePtr (64-bit offset into this file)        │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │ Radix Tree (Secondary Index)                           │   │
│   │   file_path components → [node_id, node_id, ...]        │   │
│   │   Enables "all nodes in file" queries                  │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │ String Pool (Atom Table)                                │   │
│   │   deduplicated strings: paths, names, signatures        │   │
│   │   hash32 → {offset, length}                            │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │ Node Data Region                                        │   │
│   │   Inode: {type, name_offset, sig_offset,               │   │
│   │          file_offset, line_start, line_end,           │   │
│   │          edge_list_ptr, edge_count, flags}            │   │
│   │   Fixed 64-byte entries, allocated from free list     │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │ Edge Store                                             │   │
│   │   Per-node adjacency lists                             │   │
│   │   Varint encoded: [count, [(target, type, attrs)...]] │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │ Parsed Code Cache                                       │   │
│   │   Pre-extracted AST metadata per file                  │   │
│   │   Memory-mapped, OS page cache managed                │   │
│   │   LRU eviction when memory pressure                   │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │ File Manifest                                           │   │
│   │   Fixed 128-byte entries                              │   │
│   │   {path_str_offset, hash, line_count,                 │   │
│   │    parsed_offset|0, last_modified, priority,           │   │
│   │    ref_count, status}                                 │   │
│   └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### `.smpv` Layout (Vectors)

```
┌─────────────────────────────────────────────────────────────────┐
│ Offset 0..4095: VECTOR HEADER                                   │
│   Magic: 0x534D5056 ('SMPV'), version, dim, count             │
├─────────────────────────────────────────────────────────────────┤
│ Vector Index Pages                                              │
│   node_id (64-bit) → vector_offset (64-bit)                   │
├─────────────────────────────────────────────────────────────────┤
│ Dense Float32 Embeddings                                        │
│   [dim floats] per node, appended sequentially                │
├─────────────────────────────────────────────────────────────────┤
│ LRU Metadata (mmap'd, 16 bytes per vector)                     │
│   {last_accessed_ts, access_count}                             │
└─────────────────────────────────────────────────────────────────┘
```

### Node ID Format

```
node_id = "{file_hash}::{type}::{name}::{start_line}"
Example: "a1b2c3d4::Function::login::42"

- file_hash: xxhash64 of normalized absolute path
- type: Class | Function | Method | Import | Statement | ...
- name: extracted name or synthetic (e.g., "lambda_1")
- start_line: 1-indexed line number
```

---

## Index Structures

### Crit-bit Tree (Primary Index)

- **Purpose**: Fast exact match lookups
- **Operations**: Insert, delete, find (all O(k) where k = key length)
- **Reads**: Lock-free using memory barriers
- **Writes**: Protected by WAL + single writer lock

```
Structure:
  Internal node: {child0_offset, child1_offset, crit_byte_pos}
  Leaf node: {key (node_id), value (inode_ptr)}

Lookup:
  1. Start at root
  2. At each internal node, select child based on crit_byte_pos of key
  3. Traverse until leaf
  4. Return value if key matches, else not found
```

### Radix Tree (Secondary Index)

- **Purpose**: Range queries by file path
- **Enables**: "All nodes in file F", "All nodes in directory D"

```
Structure:
  Radix node: {prefix, children {char: child_offset}, node_ids[]}

Lookup "all nodes in file F":
  1. Split F into path components
  2. Traverse radix tree following components
  3. Return union of node_ids at leaf + all ancestors
```

### String Pool (Atom Table)

- **Purpose**: Deduplicate strings (paths, names, signatures, docstrings)
- **Storage**: Length-prefixed UTF-8, 64-bit aligned

```
Structure:
  Header: {count, hash_index_offset}
  Hash Index: hash32 → [offset, length, next_collision]
  Data: raw string bytes

Lookup:
  1. Hash string → h
  2. Probe hash index at h % index_size
  3. Follow collision chain until match
  4. Return offset + length
```

---

## WAL (Write-Ahead Log)

### WAL Record Format (512 bytes each)

```
┌─────────────────────────────────────────────────────────────────┐
│ 0      : record_type (uint8)                                   │
│         0x01 = NODE_INSERT                                     │
│         0x02 = NODE_DELETE                                     │
│         0x03 = EDGE_INSERT                                     │
│         0x04 = EDGE_DELETE                                     │
│         0x05 = FILE_PARSED                                    │
│         0x06 = COMMIT                                          │
│         0x07 = CHECKPOINT                                      │
│ 1..3   : reserved                                               │
│ 4..7   : payload_size (uint32)                                │
│ 8..11  : crc32 (uint32)                                        │
│ 12..511: payload (padded to 512 bytes)                        │
└─────────────────────────────────────────────────────────────────┘
```

### Recovery Protocol

```
On startup:
1. Scan WAL from head
2. Build redo list of uncommitted records
3. Replay records in order
4. On finding COMMIT record: clear committed records from WAL
5. Truncate WAL to checkpoint

On clean shutdown:
1. Write CHECKPOINT record
2. fsync WAL
3. Write checkpoint marker in header
4. Truncate WAL
```

---

## Edge Resolution: Hybrid Approach

### Edge Candidate (Parse Time)

```
When parsing file F:
1. Extract import/call targets as NAMES (not node_ids)
2. Store edge candidate: {source_node, target_name, edge_type, target_file_hint}
3. Mark candidate as "unresolved"

target_file_hint derived from:
  - import: absolute path if resolvable
  - call: look in same file first, then imports
```

### Edge Resolution (First Traversal)

```
When traversing edge E from node A:
1. If E is resolved: follow pointer to target node
2. If E is unresolved:
   a. Look up target_name in crit-bit index
   b. If found: update E to point to real node, mark resolved
   c. If not found: return None/null, mark "unresolved"
3. Cache resolved edge in edge store
```

### Benefits

- Parse is fast (no cross-file resolution needed)
- Resolution happens lazily when path is actually traversed
- Handles dynamic imports gracefully (unresolved at first, resolved later)

---

## Parsing Engine

### Parser Interface

```python
class ParsedFile:
    file_path: str
    language: str
    line_count: int
    hash: str  # xxhash64 of content
    nodes: list[ParsedNode]
    edge_candidates: list[EdgeCandidate]
    ast_metadata: bytes  # serialized, mmap'd

class ParsedNode:
    node_id: str
    type: NodeType
    name: str
    signature: str | None
    docstring: str | None
    start_line: int
    end_line: int
    tags: list[str]
    decorators: list[str]

class EdgeCandidate:
    source_id: str
    target_name: str
    edge_type: EdgeType
    target_file_hint: str | None
```

### Supported Languages

| Language | Status | Grammar |
|----------|--------|---------|
| Python | ✅ Primary | tree-sitter-python |
| JavaScript | ✅ Supported | tree-sitter-javascript |
| TypeScript / TSX | ✅ Supported | tree-sitter-typescript |
| Java | ✅ Supported | tree-sitter-java |
| C | ✅ Supported | tree-sitter-c |
| C++ | ✅ Supported | tree-sitter-cpp |
| C# | ✅ Supported | tree-sitter-c-sharp |
| Go | ✅ Supported | tree-sitter-go |
| Rust | ✅ Supported | tree-sitter-rust |
| PHP | ✅ Supported | tree-sitter-php |
| Swift | ✅ Supported | tree-sitter-swift |
| Kotlin | ✅ Supported | tree-sitter-kotlin |
| Ruby | ✅ Supported | tree-sitter-ruby |
| MATLAB | ✅ Supported | tree-sitter-matlab |

### Scheduler (Background Pre-parse)

```
Priority Calculation:
  priority = base_priority(depth) * ref_count_factor * recency_factor

  base_priority:
    - Entry files (main.py, __init__.py): 100
    - Direct deps of entry (depth 1): 80
    - Transitive deps (depth 2-3): 60
    - Orphan files: 20

  ref_count_factor: log(1 + in_degree)
  recency_factor: 1.0 / (1 + days_since_last_access)

Worker Pool:
  - N workers (default: CPU count)
  - Work-stealing for load balancing
  - Coalesced I/O: batch read adjacent files
```

---

## Memory Management

### OS-Managed Mmap Strategy

```
Hot Set (RAM, ~10-15GB):
  - Crit-bit index pages
  - Radix tree pages
  - String pool (hot strings)
  - Node data for frequently accessed files
  - Edge lists for high-degree nodes

Warm Set (OS page cache):
  - Parsed AST metadata (accessed via mmap)
  - Node data for medium-frequency files
  - Edge lists for medium-degree nodes

Cold (Disk):
  - Parsed AST for rarely accessed files
  - Edge lists for low-degree nodes

Madvise Hints:
  - MADV_WILLNEED: when pre-parsing
  - MADV_SEQUENTIAL: for bulk import
  - MADV_DONTNEED: for eviction candidate selection
```

### LRU for Parsed Cache

```
When memory pressure detected:
1. Sort parsed regions by {last_accessed, access_count}
2. For bottom 20%:
   - madvise(DONTNEED) to release pages
   - Mark region as "evicted" in file manifest
3. Keep metadata (node boundaries, signatures) in RAM
4. Re-parse on next access if needed
```

---

## File Watcher (Live Updates)

### Hybrid Approach

```
Tier 1: inotify (primary)
  - Watch project root directories
  - Watch added/removed/changed files
  - Limit: ~500k watches typical kernel config

Tier 2: Polling fallback
  - Triggered when inotify watch limit reached
  - Poll mtime of manifest files
  - Interval: 60 seconds default

Tier 3: API invalidation
  - /smp/invalidate endpoint
  - Called by editor plugins on save
```

### Change Detection Flow

```
File F changes on disk:
1. inotify detects IN_MODIFY
2. Compare new hash vs stored hash
3. If changed:
   a. Mark FileManifest entry as "stale"
   b. Queue for background re-parse
   c. Increment priority for dependent files
4. On next query to F:
   a. Return stale cached data with "stale=true" flag
   b. Trigger async re-parse
```

---

## Query Language

### Phase 1: Path Expressions

```
Syntax:
  PATTERN := NODE_TYPE [EDGE_TYPE [NODE_TYPE]]...

  NODE_TYPE := identifier | '*'
  EDGE_TYPE := identifier | '->' | '<-' | '<->'
  identifier := [A-Za-z_][A-Za-z0-9_]*

Examples:
  Function CALLS Function           # All function calls
  Class -> DEFINES -> Method        # Methods defined in class
  * IMPORTS 'requests'              # Anything importing requests
  Function CALLS+ Function          # Transitive closure
```

### Phase 2: Filtering

```
Syntax:
  FILTER := '[' EXPRESSION ']'

  EXPRESSION := field '=' VALUE
              | field '!=' VALUE
              | field '=~' REGEX

Examples:
  Function[name='login'] CALLS Function
  Function[file_path =~ '.*/auth/.*'] CALLS+ Function
  Class[docstring =~ '(?i)abstract'] DEFINES Method
```

### Phase 3: CYPHER Subset (Future)

```
Syntax:
  MATCH (a:Type {predicates})-[r:RELATION]->(b:Type {predicates})
  WHERE conditions
  RETURN a, b [ORDER BY field LIMIT n]

Examples:
  MATCH (a:Function)-[:CALLS*1..3]->(b:Function {name: 'handler'})
  WHERE a.file_path CONTAINS 'controller'
  RETURN a.name, b.name
```

---

## GraphStore Interface Implementation

### MMapGraphStore

```python
class MMapGraphStore(GraphStore):
    """Memory-mapped graph store - drop-in GraphStore replacement"""

    # Lifecycle
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def clear(self) -> None: ...

    # Node CRUD
    async def upsert_node(self, node: GraphNode) -> None: ...
    async def upsert_nodes(self, nodes: Sequence[GraphNode]) -> None: ...
    async def get_node(self, node_id: str) -> GraphNode | None: ...
    async def delete_node(self, node_id: str) -> bool: ...
    async def delete_nodes_by_file(self, file_path: str) -> int: ...

    # Edge CRUD
    async def upsert_edge(self, edge: GraphEdge) -> None: ...
    async def upsert_edges(self, edges: Sequence[GraphEdge]) -> None: ...
    async def get_edges(self, node_id: str, edge_type: EdgeType | None, direction: str) -> list[GraphEdge]: ...

    # Traversal
    async def get_neighbors(self, node_id: str, edge_type: EdgeType | None, depth: int) -> list[GraphNode]: ...
    async def traverse(self, start_id: str, edge_type: EdgeType | list[EdgeType], depth: int, max_nodes: int, direction: str) -> list[GraphNode]: ...

    # Search
    async def find_nodes(self, *, type: NodeType | None, file_path: str | None, name: str | None) -> list[GraphNode]: ...
    async def search_nodes(self, query_terms: list[str], match: str, node_types: list[str] | None, tags: list[str] | None, scope: str | None, top_k: int) -> list[dict[str, Any]]: ...

    # Aggregation
    async def count_nodes(self) -> int: ...
    async def count_edges(self) -> int: ...

    # --- SMP Extension: Ingest-Free Operations ---

    async def parse_file(self, file_path: str) -> list[GraphNode]:
        """Parse file on-demand, extract nodes and edge candidates"""

    async def ensure_parsed(self, file_path: str) -> list[GraphNode]:
        """Parse if not already parsed, return resolved nodes with edges"""

    async def pre_parse(self, count: int, min_priority: int) -> int:
        """Background pre-parse N files at or above priority.
        Returns count of files actually parsed."""

    async def get_parse_status(self, file_path: str) -> ParseStatus:
        """Return {parsed: bool, line_count: int, node_count: int,
                  stale: bool, parse_time_ms: float | None}"""

    async def wait_for_parse(self, file_path: str, timeout: float) -> bool:
        """Block until file is fully parsed and edges resolved"""

    # --- SMP Extension: Query Language ---

    async def query(self, expression: str, params: dict | None) -> QueryResult:
        """Execute path expression query.
        Returns {nodes: [...], edges: [...], stats: {...}}"""

    # --- Session/Lock Persistence ---

    async def upsert_session(self, session: Any) -> None: ...
    async def get_session(self, session_id: str) -> dict[str, Any] | None: ...
    async def delete_session(self, session_id: str) -> bool: ...

    async def upsert_lock(self, file_path: str, session_id: str) -> None: ...
    async def get_lock(self, file_path: str) -> dict[str, Any] | None: ...
    async def release_lock(self, file_path: str, session_id: str) -> bool: ...
    async def release_all_locks(self, session_id: str) -> int: ...
```

---

## Directory Structure

```
smp/
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── models.py          # GraphNode, GraphEdge, etc. (existing)
│   └── config.py          # Settings (existing)
├── store/
│   ├── __init__.py
│   ├── interfaces.py      # GraphStore, VectorStore ABC (existing)
│   └── graph/
│       ├── __init__.py
│       ├── mmap_file.py   # Low-level mmap, WAL, header
│       ├── index.py       # Crit-bit tree + Radix tree
│       ├── string_pool.py # Atom storage
│       ├── node_store.py  # Node CRUD, inode management
│       ├── edge_store.py  # Edge storage, adjacency lists
│       ├── manifest.py    # File manifest entries
│       ├── parser.py      # tree-sitter wrapper
│       ├── scheduler.py   # Background parse scheduler
│       ├── watcher.py     # inotify + polling hybrid
│       ├── query.py       # Path expression engine
│       └── mmap_store.py  # MMapGraphStore implementation
├── engine/
│   ├── __init__.py
│   ├── graph_builder.py   # Modify for mmap_store
│   └── query.py          # Modify for ingest-free
├── protocol/
│   ├── __init__.py
│   ├── server.py          # Update to use mmap_store
│   └── handlers/
│       ├── __init__.py
│       ├── memory.py      # Update for source content
│       └── query.py       # Update query endpoint
├── vector/
│   ├── __init__.py
│   └── mmap_vector.py    # .smpv implementation
└── cli.py                 # Update commands
```

---

## Implementation Phases

### Phase 1: Core Infrastructure (2-3 weeks)

| Task | Description |
|------|-------------|
| 1.1 | Define binary format, implement `mmap_file.py` header read/write |
| 1.2 | Implement WAL with crash recovery |
| 1.3 | Implement Crit-bit tree (lock-free reads) |
| 1.4 | Implement Radix tree (secondary index) |
| 1.5 | Implement String pool with deduplication |
| 1.6 | Basic MMapGraphStore skeleton with empty implementations |

**Milestone**: Can create/open empty graph file, basic sanity tests pass.

### Phase 2: Parsing Engine (2 weeks)

| Task | Description |
|------|-------------|
| 2.1 | tree-sitter Python parser wrapper |
| 2.2 | Parse file → extract nodes + edge candidates |
| 2.3 | Implement file manifest |
| 2.4 | Implement LRU eviction for parsed cache |
| 2.5 | Implement scheduler with priority queue |
| 2.6 | `parse_file()` and `ensure_parsed()` |

**Milestone**: Can parse Python file on-demand, see nodes in graph.

### Phase 3: Graph Operations (2 weeks)

| Task | Description |
|------|-------------|
| 3.1 | Node store with inode allocation |
| 3.2 | Edge store with varint encoding |
| 3.3 | Implement edge resolution (hybrid) |
| 3.4 | Implement `upsert_node`, `get_node`, `delete_node` |
| 3.5 | Implement `get_edges`, `get_neighbors`, `traverse` |
| 3.6 | Implement `find_nodes`, `search_nodes` |

**Milestone**: Can insert nodes, traverse edges, CRUD operations work.

### Phase 4: Query Language (1-2 weeks)

| Task | Description |
|------|-------------|
| 4.1 | Path expression parser |
| 4.2 | Pattern matching engine |
| 4.3 | Implement `query()` method |
| 4.4 | Phase 2 filtering syntax |

**Milestone**: Can query with `Function CALLS Function` style expressions.

### Phase 5: Vector Store (1-2 weeks)

| Task | Description |
|------|-------------|
| 5.1 | Define `.smpv` format |
| 5.2 | Implement vector index + storage |
| 5.3 | Embedding generation service integration |
| 5.4 | Similarity search |

**Milestone**: Can store embeddings, query by similarity.

### Phase 6: Live Updates (1 week)

| Task | Description |
|------|-------------|
| 6.1 | inotify integration |
| 6.2 | Polling fallback |
| 6.3 | Stale detection + re-parse |

**Milestone**: Graph stays in sync with file system changes.

### Phase 7: Integration & Polish (2 weeks)

| Task | Description |
|------|-------------|
| 7.1 | Replace Neo4j in server.py |
| 7.2 | Update handlers for direct source content |
| 7.3 | Remove Neo4j dependencies |
| 7.4 | Performance testing at scale |
| 7.5 | Documentation |

**Milestone**: Full system working without Neo4j.

---

## Performance Targets

| Operation | Target | Notes |
|-----------|--------|-------|
| Index lookup | <1ms | Point query in crit-bit |
| File parse (1K LOC) | <100ms | tree-sitter parse |
| Edge resolution | <10ms | Target in RAM |
| Traverse depth 3 | <50ms | BFS with early exit |
| First query (unparsed file) | <200ms | Parse + index update |
| Subsequent queries | <10ms | Already in RAM |
| WAL replay (10K ops) | <1s | After crash |
| Bulk import (10K files) | <60s | With parallel workers |

---

## Testing Strategy

### Unit Tests

```
tests/
├── store/graph/
│   ├── test_mmap_file.py      # Header, WAL, crash recovery
│   ├── test_index.py          # Crit-bit, radix tree
│   ├── test_string_pool.py    # Deduplication, collisions
│   ├── test_node_store.py     # CRUD, allocation
│   ├── test_edge_store.py     # Varint encoding, adjacency
│   ├── test_manifest.py       # File entries
│   └── test_mmap_store.py     # Full integration
├── parser/
│   ├── test_parser.py         # tree-sitter output
│   └── test_scheduler.py      # Priority queue
├── query/
│   ├── test_path_parser.py    # Expression parsing
│   └── test_query_engine.py   # Pattern matching
└── vector/
    └── test_mmap_vector.py    # Vector CRUD, similarity
```

### Integration Tests

```
tests/integration/
├── test_ingest_free.py        # Query unparsed file → parse → query
├── test_multi_file.py         # Cross-file edges
├── test_concurrent.py         # Read + write simultaneously
├── test_crash_recovery.py     # Simulated crash + replay
└── test_large_scale.py        # 10K+ nodes stress test
```

### Benchmarks

```
benchmarks/
├── benchmark_index.py         # Crit-bit performance
├── benchmark_parse.py         # Parse throughput
├── benchmark_traverse.py      # Graph traversal
└── benchmark_scale.py         # Memory usage at scale
```

---

## Dependencies

```python
# Core
tree-sitter>=0.21.0
tree-sitter-python>=0.21.0

# Optional (for vector embeddings)
numpy>=1.24.0  # Vector storage
sentence-transformers>=2.2.0  # Embedding generation

# File watching
pyinotify>=0.9.6  # Linux inotify

# Testing
pytest>=7.4.0
pytest-asyncio>=0.21.0
pytest-benchmark>=4.0.0
```

---

## Future Extensions

### Language Support

All 14 languages listed below are fully supported through the `CodeParser` → `ParserRegistry` bridge:

| Language | tree-sitter grammar | Status |
|----------|---------------------|--------|
| Python | tree-sitter-python | ✅ Primary (native walker) |
| JavaScript | tree-sitter-javascript | ✅ Supported |
| TypeScript / TSX | tree-sitter-typescript | ✅ Supported |
| Java | tree-sitter-java | ✅ Supported |
| C | tree-sitter-c | ✅ Supported |
| C++ | tree-sitter-cpp | ✅ Supported |
| C# | tree-sitter-c-sharp | ✅ Supported |
| Go | tree-sitter-go | ✅ Supported |
| Rust | tree-sitter-rust | ✅ Supported |
| PHP | tree-sitter-php | ✅ Supported |
| Swift | tree-sitter-swift | ✅ Supported |
| Kotlin | tree-sitter-kotlin | ✅ Supported |
| Ruby | tree-sitter-ruby | ✅ Supported |
| MATLAB | tree-sitter-matlab | ✅ Supported |

### Features

- **Incremental parsing**: Re-use AST for small changes
- **Remote graphs**: Graph file served over network
- **Replication**: Primary + read replicas
- **Full-text search**: Enhanced FTS in string pool
- **Graph algorithms**: PageRank, connected components, cycle detection
