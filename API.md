# Structural Memory Protocol (SMP) – API Reference

**Version:** 1.0  
**Transport:** JSON-RPC 2.0 over HTTP (POST `/rpc`) or WebSockets  
**Content-Type:** `application/json`

The Structural Memory Protocol (SMP) is a framework designed to give AI agents a "programmer's brain". It exposes a comprehensive, production-ready JSON-RPC 2.0 API that provides structural graph understanding, isolated sandbox execution, telemetry, and safe write mechanisms for agent swarms.

---

## Table of Contents

1. [Protocol Basics](#protocol-basics)
2. [Memory & Sync](#memory--sync)
3. [Index Distribution](#index-distribution)
4. [Linker & Resolution](#linker--resolution)
5. [Enrichment & Annotation](#enrichment--annotation)
6. [Structural Queries](#structural-queries)
7. [Planning & Conflict Detection](#planning--conflict-detection)
8. [Community Detection (Graph RAG)](#community-detection-graph-rag)
9. [Session & Agent Safety](#session--agent-safety)
10. [Telemetry](#telemetry)
11. [Sandbox Runtime](#sandbox-runtime)
12. [Swarm Handoff](#swarm-handoff)
13. [Server Notifications](#server-notifications)
14. [Error Codes](#error-codes)

---

## Protocol Basics

All requests to the SMP server must conform to the JSON-RPC 2.0 specification. 

**Standard Request:**
```json
{
  "jsonrpc": "2.0",
  "method": "smp/method_name",
  "params": { "key": "value" },
  "id": 1
}
```

**Standard Success Response:**
```json
{
  "jsonrpc": "2.0",
  "result": { "data": "..." },
  "id": 1
}
```

**Standard Error Response:**
```json
{
  "jsonrpc": "2.0",
  "error": {
    "code": -32001,
    "message": "Node not found",
    "data": { "node_id": "func_invalid" }
  },
  "id": 1
}
```

---

## Memory & Sync

Manage the state of the codebase and sync the Merkle tree for offline diffing.

### `smp/update`
Sync an individual file change to the graph memory.

* **Params:**
  * `type` (string): Fixed to `"file_change"`.
  * `file_path` (string): Path to the file.
  * `content` (string): The raw source code of the file.
  * `change_type` (string): `"modified"`, `"created"`, or `"deleted"`.
* **Result:** Status and counts of nodes/edges updated.

### `smp/batch_update`
Apply changes to multiple files simultaneously.

* **Params:**
  * `changes` (array of objects): Array containing `file_path`, `content`, and `change_type`.
* **Result:** Aggregated update statistics.

### `smp/sync`
O(log n) Merkle-diff sync. Compares client hashes against the server's Merkle tree and returns exactly which files need pushing/pulling.

* **Params:**
  * `client_root_hash` (string): SHA-256 root hash of the client's tree.
  * `file_hashes` (object): Flat map of `{"file_path": "sha256_hash"}`.
* **Result:** The minimal diff (`stale_on_server`, `missing_on_client`, `deleted_on_server`).

### `smp/merkle/tree`
Returns the server's full Merkle tree. Used by agents to build a local copy for offline diffs.

* **Params:**
  * `scope` (string): `"full"` or `"package:<path>"`.
* **Result:** A hierarchical JSON representation of the SHA-256 tree.

---

## Index Distribution

For fast agent onboarding and multi-instance SMP deployments.

### `smp/index/export`
Packages the current graph and vector index as a signed, portable snapshot.

* **Params:**
  * `scope` (string): `"full"` or `"package:<path>"`.
  * `signing_key_id` (string): Key ID to sign the snapshot.
* **Result:** `snapshot_id`, `root_hash`, and the `export_url`.

### `smp/index/import`
Loads a signed snapshot. Verifies signature and root hash before touching the graph. Re-indexes only diverging subtrees if hashes do not perfectly match.

* **Params:**
  * `snapshot_id` (string): ID of the snapshot.
  * `source_url` (string): URL/path to the `.tar.zst` snapshot.
  * `expected_root_hash` (string): The hash the client expects.
  * `verify_signature` (boolean): Enforce cryptographic signature check.
* **Result:** Import status (`imported`, `partial_import`) and duration.

---

## Linker & Resolution

Resolves namespaced imports to concrete structural paths, and captures eBPF runtime data.

### `smp/linker/report`
Lists all unresolved static edges (e.g., ambiguous calls where the target function exists in multiple files but wasn't explicitly imported).

* **Params:**
  * `scope` (string): `"full"`, `"package:<path>"`, or `"file:<path>"`.
* **Result:** Array of `unresolved` edge definitions indicating caller and candidates.

### `smp/linker/runtime`
Retrieves all `CALLS_RUNTIME` edges for a node (captured via eBPF trace execution).

* **Params:**
  * `node_id` (string): Target node ID.
  * `commit_sha` (string): Specific commit hash.
* **Result:** Arrays of `runtime_callees` and `static_only_callees`.

---

## Enrichment & Annotation

Extract static metadata (docstrings, type hints) and generate semantic search indexes without LLMs.

### `smp/enrich`
Extracts static metadata from a specific node's AST.

* **Params:**
  * `node_id` (string): The ID of the node.
  * `force` (boolean, default: `false`): Re-enrich even if source hash is unchanged.
* **Result:** Extracted `docstring`, `decorators`, `annotations`, and tags. Status will be `enriched`, `skipped`, or `no_metadata`.

### `smp/enrich/batch`
Enriches all nodes within a given scope.

* **Params:**
  * `scope` (string): `"full"`, `"package:<path>"`, or `"file:<path>"`.
  * `force` (boolean, default: `false`).
* **Result:** Counts of nodes enriched, skipped, and missing metadata.

### `smp/enrich/stale` / `smp/enrich/status`
Retrieves a list of nodes whose source hash changed since last enrichment, or returns the overall coverage report.

### `smp/annotate` & `smp/annotate/bulk`
Manually set metadata (descriptions, tags) on nodes that have no extractable metadata. Will return a conflict error if attempting to overwrite an automatically extracted docstring without `force: true`.

### `smp/tag`
Bulk-apply or remove tags across a structural scope.

* **Params:**
  * `scope` (string).
  * `tags` (array of strings).
  * `action` (string): `"add"`, `"remove"`, or `"replace"`.

### `smp/search`
BM25-ranked full-text search against the enriched neo4j index.

* **Params:**
  * `query` (string): Keywords.
  * `match` (string): `"all"` (AND) or `"any"` (OR).
  * `filter` (object, optional): `node_types`, `tags`, `scope`.
  * `top_k` (integer): Result limit.
* **Result:** Array of matched nodes with their `bm25_score`.

---

## Structural Queries

The core Query Engine used by agents to build their mental models.

### `smp/context`
Provides the "programmer's mental model" of a file, computing its role, blast radius, dependencies, and entry points.

* **Params:**
  * `file_path` (string).
  * `scope` (string): `"edit"`, `"create"`, `"debug"`, or `"review"`.
  * `depth` (int, default: 2): Traversal depth.
* **Result:** `summary`, `self`, `imports`, `imported_by`, `defines`, `data_flow_in`, `data_flow_out`.

### `smp/navigate` & `smp/trace`
Find entities by name and follow their relationship chains up to a specific depth.

### `smp/impact`
Assess what breaks if a given node is modified, moved, or deleted.

* **Params:**
  * `entity` (string): Node ID.
  * `change_type` (string): `"signature_change"`, `"delete"`, `"move"`.
* **Result:** Affected files/functions and `required_updates`.

### `smp/flow`
Trace data or execution paths between two structural nodes.

### `smp/diff`
Compare the current graph state of a file against proposed new content. Returns the exact node and edge differences.

* **Params:**
  * `file_path` (string).
  * `proposed_content` (string).
* **Result:** `nodes_added`, `nodes_removed`, `nodes_modified`, and relationship deltas.

### `smp/graph/why`
Explains the shortest dependency path between two nodes in plain text and edge arrays.

---

## Planning & Conflict Detection

### `smp/plan`
Validate and risk-rank a multi-file task before execution.

* **Params:**
  * `session_id` (string).
  * `task` (string): The agent's intent.
  * `intended_writes` (array of strings): File paths.
* **Result:** Recommended `execution_order` sorted by dependency topology, and risk indicators.

### `smp/conflict`
Detect if two active agent sessions overlap in scope.

---

## Community Detection (Graph RAG)

Topology-based codebase partitioning and semantic routing.

### `smp/community/detect`
Runs the Louvain algorithm to partition the graph into Coarse (L0) and Fine (L1) communities. Calculates centroid embeddings for routing.

* **Params:**
  * `algorithm` (string): `"louvain"`.
  * `relationship_types` (array of strings).
  * `levels` (array of objects defining `resolution`).
* **Result:** Community discovery statistics and hierarchies.

### `smp/locate`
The primary code discovery endpoint. Uses Community-Routed Graph RAG.

* **Params:**
  * `query` (string): Natural language.
  * `seed_k` (int, default: 3): Initial ChromaDB vector seeds.
  * `hops` (int, default: 2): Graph traversal depth from seeds.
  * `top_k` (int, default: 10): Final ranked limit.
  * `community_id` (string, optional): Bypass Phase 0 auto-routing.
* **Result:** `LocateResponse` containing a ranked list based on composite scoring (Vector + PageRank + Heat) and a `structural_map`.

### `smp/community/boundaries`
Calculates coupling strength between domain architectures.

* **Params:**
  * `level` (int): `0` (coarse) or `1` (fine).
  * `min_coupling` (float).
* **Result:** Pairs of communities, `coupling_weight`, and the specific `bridge_nodes` causing the dependency.

---

## Session & Agent Safety

SMP acts as the guardrail layer. Agents must talk to SMP before touching the codebase.

### `smp/session/open`
Declare write intent, isolate a workspace snapshot, and receive safety clearance.

* **Params:**
  * `agent_id` (string).
  * `task` (string).
  * `scope` (array of strings): Files to be touched.
  * `mode` (string): `"write"` or `"read"`.
  * `commit_sha` (string): Base snapshot.
  * `concurrency` (string): `"mvcc"` (parallel) or `"exclusive"` (file-locks).
* **Result:** `session_id`, `granted_scope`, and an auto-calculated `safety_level`.

### `smp/guard/check`
Pre-flight check against tests, blast radius, and locking before modifying a file.

* **Params:**
  * `session_id` (string).
  * `target` (string): File to modify.
  * `intended_change` (string).
* **Result:** `verdict` (`"clear"`, `"red_alert"`, `"blocked"`), blocking conditions, and unblock requirements (e.g., write tests first).

### `smp/dryrun`
Simulates a file write and checks for structural breakages.

* **Params:**
  * `session_id` (string).
  * `file_path` (string).
  * `proposed_content` (string).
* **Result:** `verdict` (`"safe"`, `"breaking"`) and list of broken callers/tests.

### `smp/checkpoint` & `smp/rollback`
Snapshot the graph state of a file, and restore it if an agent goes down the wrong path.

### `smp/session/close`
Commit the session, write to the audit log, and drop locks.

### `smp/audit/get`
Retrieve the full step-by-step history of a session ID.

---

## Telemetry

Tracks how structural nodes change over time. Highly-changed nodes with many callers are flagged as "Hot Nodes".

### `smp/telemetry/record`
*(Internal/System)* Records an agent write. Fired automatically by `smp/update`.

### `smp/telemetry/hot`
Get nodes with high churn AND high dependency counts.

* **Params:**
  * `scope` (string).
  * `window_days` (int).
  * `min_changes` (int).
  * `min_callers` (int).
* **Result:** Ranked list of nodes by `heat_score`.

### `smp/telemetry/node`
View the complete modification history of a specific node.

---

## Sandbox Runtime

Ephemeral microVMs or containers with Copy-on-Write (CoW) filesystems and strict networking.

### `smp/sandbox/spawn`
Request an isolated execution environment.

* **Params:**
  * `session_id` (string).
  * `commit_sha` (string).
  * `image` (string).
  * `services` (array of strings, e.g., `["postgres:15"]`).
  * `cow_fs_clone` (boolean).
  * `inject_ebpf` (boolean).
* **Result:** `sandbox_id` and network policies.

### `smp/sandbox/execute`
Run a shell command inside the sandbox. Automatically parses network blocks and injects `CALLS_RUNTIME` edges discovered by eBPF.

* **Params:**
  * `sandbox_id` (string).
  * `command` (string).
  * `timeout_ms` (int).
* **Result:** `exit_code`, `stdout`, `stderr`, and `calls_runtime_injected`.

### `smp/verify/integrity`
The final code-quality gate. Runs an AST data-flow assert check and deterministic mutation testing.

* **Params:**
  * `sandbox_id` (string).
  * `target_file` (string).
  * `test_file` (string).
* **Result:** Mutants killed vs. survived, and final `status` (`"passed"`, `"failed"`).

### `smp/sandbox/destroy`
Tears down the environment.

---

## Swarm Handoff

### `smp/handoff/review`
Pass a verified sandbox to a peer-reviewer agent.

* **Params:**
  * `sandbox_id` (string).
  * `session_id` (string).
  * `reviewer_agent` (string).
  * `verify_result_id` (string).
* **Result:** `handoff_id` and status.

### `smp/handoff/pr`
Package verified agent work as a Pull Request, injecting structural telemetry into the description.

* **Params:**
  * `sandbox_id` (string).
  * `session_id` (string).
  * `title` (string).
  * `include` (object): Flags to include `structural_diff`, `mutation_score`, etc.
* **Result:** `pr_id`, base/head shas, and a generated diff summary.

---

## Server Notifications

SMP Server can push notifications asynchronously (via WebSocket) to agents.

* **`memory_updated`**: Graph updated by another agent.
* **`conflict_detected`**: Scope overlap.
* **`lock_conflict`**: Sequential lock blocked.
* **`scope_violation`**: Agent attempted to touch a file outside its `session/open` declaration.
* **`session_expired`**: TTL elapsed, locks released.
* **`network_blocked`**: Sandbox firewall blocked an external request.
* **`handoff_accepted`**: Peer agent began reviewing the sandbox.

---

## Error Codes

| Code | Message | Description |
| :--- | :--- | :--- |
| `-32600` | Invalid Request | JSON parsing error. |
| `-32601` | Method not found | The requested SMP method does not exist. |
| `-32001` | Node not found | The specified `node_id` does not exist in the graph. |
| `-32002` | Conflict | Attempted to overwrite a docstring without `force: true`. |
| `-32010` | Signature Invalid | `smp/index/import` cryptographic check failed. |
| `-32020` | Session Denied | Could not allocate agent session. |
| `-32021` | Safety Block | `smp/guard/check` triggered a hard block. |
| `-32030` | Sandbox Error | Failed to spawn or communicate with the execution runtime. |