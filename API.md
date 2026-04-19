# API Reference: Structural Memory Protocol (SMP)

SMP exposes a **JSON-RPC 2.0** API. All requests must be sent as POST requests to `/rpc` with `Content-Type: application/json`.

## 📡 General Request Format
```json
{
  "jsonrpc": "2.0",
  "method": "smp/method_name",
  "params": { ... },
  "id": 1
}
```

---

## 🔍 Discovery & Search

### `smp/locate`
Finds relevant code entities using Community-Routed Graph RAG.
- **Params:**
    - `query` (string): The natural language description of what to find.
    - `seed_k` (int, optional): Number of initial vector seeds. Default: 3.
    - `hops` (int, optional): Depth of graph traversal. Default: 2.
    - `top_k` (int, optional): Number of final results. Default: 10.
- **Returns:** `LocateResponse` containing ranked results and a structural map of relationships.

### `smp/search`
BM25-ranked full-text search across enriched metadata.
- **Params:**
    - `query` (string): Keywords to search.
    - `match` (string): `"all"` (AND) or `"any"` (OR).
    - `filter` (object, optional):
        - `node_types` (list): e.g., `["Function", "Class"]`.
        - `tags` (list): e.g., `["billing"]`.
        - `scope` (string): e.g., `"package:src/payments"`.
    - `top_k` (int): Number of results.
- **Returns:** List of matches ranked by BM25 score.

---

## 🛠 Enrichment & Annotation

### `smp/enrich`
Extracts static metadata (docstrings, decorators) from a specific node.
- **Params:**
    - `node_id` (string): ID of the node to enrich.
    - `force` (bool, optional): Re-enrich even if source hash is unchanged.
- **Returns:** Extracted metadata or status (`enriched`, `skipped`, `no_metadata`).

### `smp/enrich/batch`
Enriches all nodes within a given scope.
- **Params:**
    - `scope` (string): `"full"`, `"package:<path>"`, or `"file:<path>"`.
    - `force` (bool): Force re-enrichment.
- **Returns:** Counts of enriched, skipped, and failed nodes.

### `smp/enrich/stale`
Lists nodes whose source code has changed since the last enrichment.
- **Params:** `scope` (string).
- **Returns:** List of stale nodes with `current_hash` vs `enriched_hash`.

### `smp/annotate`
Manually set metadata on a node (used for `no_metadata` nodes).
- **Params:**
    - `node_id` (string).
    - `description` (string).
    - `tags` (list[string]).
- **Returns:** Confirmation of annotation.

### `smp/tag`
Bulk-apply or remove tags across a scope.
- **Params:**
    - `scope` (string).
    - `tags` (list[string]).
    - `action` (string): `"add"`, `"remove"`, or `"replace"`.

---

## 🌐 Community & Architecture

### `smp/community/detect`
Runs the Louvain algorithm to partition the codebase into Coarse (L0) and Fine (L1) communities.
- **Params:**
    - `algorithm` (string): `"louvain"`.
    - `relationship_types` (list): Types to consider (e.g., `["CALLS_STATIC", "IMPORTS"]`).
    - `levels` (list): Resolution settings for L0 and L1.
- **Returns:** Community statistics and list of detected communities.

### `smp/community/list`
Lists all detected communities.
- **Params:** `level` (int): `0` (coarse), `1` (fine), or omit for both.
- **Returns:** List of community objects (labels, member counts, etc.).

### `smp/community/get`
Gets all nodes within a specific community.
- **Params:**
    - `community_id` (string).
    - `node_types` (list, optional).
    - `include_bridges` (bool): Include edges crossing into other communities.

### `smp/community/boundaries`
Calculates coupling strength between community pairs.
- **Params:**
    - `level` (int): `0` or `1`.
    - `min_coupling` (float): Filter out pairs below this weight.
- **Returns:** Coupling weights and the specific "bridge nodes" responsible for the coupling.

---

## 🧠 Agent Context

### `smp/context`
The primary method for agents to get a "mental model" of a file.
- **Params:**
    - `file_path` (string).
    - `scope` (string): `"edit"`, `"review"`, or `"architect"`.
    - `depth` (int): Traversal depth for related patterns.
- **Returns:** A comprehensive context object containing:
    - `self`: The file node.
    - `imports` / `imported_by`: Dependency graph.
    - `defines`: Symbols defined in the file.
    - `summary`: A pre-computed structural summary (blast radius, complexity, heat score).

---

## ⚠️ Error Codes

| Code | Message | Description |
| :--- | :--- | :--- |
| `-32600` | Invalid Request | JSON parsing error. |
| `-32601` | Method not found | The requested SMP method does not exist. |
| `-32001` | Node not found | The specified `node_id` does not exist in the graph. |
| `-32002` | Conflict | Attempted to overwrite a docstring without `force: true`. |
