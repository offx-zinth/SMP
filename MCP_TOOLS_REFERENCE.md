# SMP MCP Tools Reference

Quick reference for all 49+ MCP tools available in SMP, organized by category.

## Query & Navigation (7 tools)

### `smp/navigate`
Find an entity and return basic info with relationships.
- **Params:** `query: str`, `include_relationships?: bool`
- **Returns:** Node info with edges
- **Use:** Find a function, class, or file

### `smp/trace`
Follow a chain of relationships from a starting node.
- **Params:** `start: str`, `relationship?: str`, `depth?: int`, `direction?: str`
- **Returns:** List of nodes along the path
- **Use:** Trace call chains, imports, inheritance hierarchies

### `smp/context`
Get surrounding context for safe editing (programmer's mental model).
- **Params:** `file_path: str`, `scope?: str`, `depth?: int`
- **Returns:** Surrounding nodes and structure
- **Use:** Understand what needs to be edited together

### `smp/impact`
Assess the blast radius of a change.
- **Params:** `entity: str`, `change_type?: str`
- **Returns:** All affected nodes
- **Use:** Before deleting/modifying, understand impact

### `smp/locate`
Find code entities by keyword search.
- **Params:** `query: str`, `fields?: list[str]`, `node_types?: list[str]`, `top_k?: int`
- **Returns:** Ranked matches
- **Use:** Find all functions matching a pattern

### `smp/search`
Semantic search across docstrings and tags.
- **Params:** `query: str`, `match?: str`, `filters?: dict`, `top_k?: int`
- **Returns:** Ranked results with scores
- **Use:** Find related functionality

### `smp/flow`
Trace execution or data flow between entities.
- **Params:** `start: str`, `end: str`, `flow_type?: str`
- **Returns:** Paths between nodes
- **Use:** Find how data/control flows through code

---

## Advanced Query (4 tools)

### `smp/diff`
Analyze differences between entities.
- **Params:** `entity1: str`, `entity2: str`
- **Returns:** Diff analysis
- **Use:** Compare functions, classes, or file versions

### `smp/plan`
Plan changes and get impact preview.
- **Params:** `changes: list[dict]`
- **Returns:** Plan with impact analysis
- **Use:** Preview multi-step changes

### `smp/conflict`
Detect potential conflicts in changes.
- **Params:** `changes: list[dict]`
- **Returns:** Conflicts found
- **Use:** Detect write conflicts before committing

### `smp/why`
Explain why a relationship exists.
- **Params:** `source: str`, `target: str`, `relationship: str`
- **Returns:** Explanation/justification
- **Use:** Understand why code depends on something

---

## Memory & Updates (3 tools)

### `smp/update`
Ingest or update a single file.
- **Params:** `file_path: str`, `content?: str`, `language?: str`
- **Returns:** `{ file_path, nodes, edges, errors }`
- **Use:** Parse new file or re-parse existing

### `smp/batch_update`
Update multiple files at once.
- **Params:** `changes: list[UpdateParams]`
- **Returns:** `{ updates, results }`
- **Use:** Bulk ingest after directory changes

### `smp/reindex`
Rebuild parts of the graph index.
- **Params:** `scope?: str`
- **Returns:** `{ status, scope }`
- **Use:** After major bulk changes

---

## Enrichment & Annotation (7 tools)

### `smp/enrich`
Extract and store semantic metadata for a node.
- **Params:** `node_id: str`, `force?: bool`
- **Returns:** Enriched metadata (docstring, comments, decorators, tags)
- **Use:** Generate docstring summaries, extract type hints

### `smp/enrich/batch`
Batch enrich multiple nodes.
- **Params:** `node_ids: list[str]`, `force?: bool`
- **Returns:** `{ enriched, failed }`
- **Use:** Bulk metadata generation

### `smp/enrich/stale`
Find nodes that need re-enrichment.
- **Params:** `days?: int`, `limit?: int`
- **Returns:** List of stale nodes
- **Use:** Identify outdated metadata

### `smp/enrich/status`
Check enrichment coverage across the graph.
- **Params:** (none)
- **Returns:** Coverage statistics
- **Use:** Monitor enrichment progress

### `smp/annotate`
Manually annotate a node with description and tags.
- **Params:** `node_id: str`, `description: str`, `tags?: list[str]`, `force?: bool`
- **Returns:** `{ node_id, status, annotated_at }`
- **Use:** Add custom documentation

### `smp/annotate/bulk`
Bulk annotate multiple nodes.
- **Params:** `annotations: list[AnnotateParams]`
- **Returns:** `{ annotated, failed }`
- **Use:** Batch add custom metadata

### `smp/tag`
Add, remove, or replace tags on a scope.
- **Params:** `scope: str`, `tags: list[str]`, `action: "add"|"remove"|"replace"`
- **Returns:** `{ nodes_affected, action, scope }`
- **Use:** Bulk categorize code (e.g., "deprecated", "api")

---

## Community Detection (4 tools)

### `smp/community/detect`
Run community detection on the graph.
- **Params:** `resolutions?: list[float]`, `relationship_types?: list[str]`
- **Returns:** Community structure
- **Use:** Analyze architectural boundaries

### `smp/community/list`
List all detected communities.
- **Params:** `level?: int`
- **Returns:** List of communities with node counts
- **Use:** See high-level architecture

### `smp/community/get`
Get detailed info for a specific community.
- **Params:** `community_id: str`, `node_types?: list[str]`, `include_bridges?: bool`
- **Returns:** Community members, bridges, internal edges
- **Use:** Understand module structure

### `smp/community/boundaries`
Get coupling metrics between communities.
- **Params:** `level?: int`, `min_coupling?: float`
- **Returns:** Inter-community edges and coupling weights
- **Use:** Find high-coupling modules

---

## Synchronization & Integrity (4 tools)

### `smp/sync`
Perform Merkle tree sync (O(log n) incremental).
- **Params:** `remote_hash?: str`
- **Returns:** Sync manifest
- **Use:** Sync graph to new agents

### `smp/merkle/tree`
Get the current Merkle tree structure.
- **Params:** (none)
- **Returns:** Tree structure and hashes
- **Use:** Verify graph integrity

### `smp/merkle/export`
Export the Merkle index for distribution.
- **Params:** `format?: str`
- **Returns:** Exportable index
- **Use:** Ship index snapshot

### `smp/merkle/import`
Import a Merkle index snapshot.
- **Params:** `index: dict`
- **Returns:** `{ status, nodes_imported }`
- **Use:** Restore from snapshot

---

## Safety & Sessions (11 tools)

### `smp/session/open`
Create a new safety session.
- **Params:** `agent_id?: str`, `workspace?: str`
- **Returns:** `{ session_id, created_at }`
- **Use:** Start isolated edit session

### `smp/session/close`
Close a session.
- **Params:** `session_id: str`, `commit?: bool`
- **Returns:** `{ session_id, status }`
- **Use:** Finalize or discard changes

### `smp/session/recover`
Recover a crashed session.
- **Params:** `session_id: str`
- **Returns:** Session state
- **Use:** Resume interrupted work

### `smp/guard/check`
Check against safety guards (policy rules).
- **Params:** `node_id: str`, `action: str`
- **Returns:** `{ allowed: bool, reason? }`
- **Use:** Verify permission before action

### `smp/dryrun`
Simulate a change without committing.
- **Params:** `changes: list[dict]`
- **Returns:** Simulation result with impact
- **Use:** Preview before executing

### `smp/checkpoint`
Create a recovery checkpoint.
- **Params:** `session_id: str`, `name?: str`
- **Returns:** `{ checkpoint_id, created_at }`
- **Use:** Save state for rollback

### `smp/rollback`
Restore to a checkpoint.
- **Params:** `checkpoint_id: str`
- **Returns:** `{ status, restored_nodes }`
- **Use:** Undo to safe state

### `smp/lock`
Lock nodes to prevent concurrent edits.
- **Params:** `node_ids: list[str]`, `session_id: str`, `ttl?: int`
- **Returns:** `{ locked, conflicts? }`
- **Use:** Prevent race conditions

### `smp/unlock`
Release node locks.
- **Params:** `node_ids: list[str]`, `session_id: str`
- **Returns:** `{ unlocked }`
- **Use:** Release held locks

### `smp/audit/get`
Retrieve audit log entries.
- **Params:** `session_id?: str`, `limit?: int`, `offset?: int`
- **Returns:** Audit entries with timestamps
- **Use:** Review what changed

### `smp/integrity/verify`
Verify structural integrity of nodes.
- **Params:** `node_ids?: list[str]`, `strict?: bool`
- **Returns:** `{ valid: bool, errors? }`
- **Use:** Detect corruption

---

## Sandbox & Execution (3 tools)

### `smp/sandbox/spawn`
Create an isolated execution environment.
- **Params:** `runtime?: str`, `isolation?: str`, `memory_mb?: int`
- **Returns:** `{ sandbox_id, ready: bool }`
- **Use:** Safe code execution

### `smp/sandbox/execute`
Run commands in sandbox.
- **Params:** `sandbox_id: str`, `command: str`, `timeout?: int`
- **Returns:** `{ stdout, stderr, exit_code }`
- **Use:** Test code changes

### `smp/sandbox/destroy`
Tear down sandbox.
- **Params:** `sandbox_id: str`
- **Returns:** `{ status }`
- **Use:** Cleanup

---

## Coordination & Handoff (2 tools)

### `smp/handoff/review`
Create a code review handoff.
- **Params:** `changes: list[dict]`, `assignee?: str`
- **Returns:** `{ review_id, status }`
- **Use:** Request review before commit

### `smp/handoff/pr`
Create a pull request.
- **Params:** `title: str`, `description: str`, `files: list[str]`, `target?: str`
- **Returns:** `{ pr_id, url }`
- **Use:** Formal change submission

---

## Observability (4 tools)

### `smp/telemetry`
Query general telemetry data.
- **Params:** `start?: str`, `end?: str`, `granularity?: str`
- **Returns:** Metrics over time
- **Use:** Monitor performance

### `smp/telemetry/hot`
Find hot paths (frequently traversed).
- **Params:** `limit?: int`
- **Returns:** Hot nodes/edges with hit counts
- **Use:** Identify critical paths

### `smp/telemetry/node`
Get detailed metrics for a node.
- **Params:** `node_id: str`
- **Returns:** Hit count, latency, errors
- **Use:** Profile node performance

### `smp/telemetry/record`
Record a custom telemetry event.
- **Params:** `event_name: str`, `tags?: dict`, `value?: float`
- **Returns:** `{ recorded_at }`
- **Use:** Custom monitoring

---

## Summary by Use Case

### I want to understand code structure
→ Use: `navigate`, `trace`, `context`, `community/get`

### I want to find something
→ Use: `locate`, `search`, `find_flow`

### I want to know if my change is safe
→ Use: `impact`, `assess_impact`, `plan`, `conflict`, `dryrun`

### I want to edit code safely
→ Use: `session/open`, `lock`, `checkpoint`, `guard/check`, `dryrun`, `session/close`

### I want to refresh understanding
→ Use: `update`, `enrich`, `enrich/batch`

### I want to categorize code
→ Use: `tag`, `annotate`, `community/detect`

### I want to coordinate with others
→ Use: `session/open`, `handoff/review`, `handoff/pr`, `lock`

### I want to ensure integrity
→ Use: `integrity/verify`, `sync`, `merkle/tree`, `audit/get`

---

## Tool Discovery

All tools are auto-discoverable via MCP's `tools/list` endpoint:
```
{
  "tools": [
    {
      "name": "smp_navigate",
      "description": "Find an entity and its relationships",
      "inputSchema": { ... }
    },
    ...
  ]
}
```

