---
name: smp
description: Live structural code graph over MCP. Use whenever working in a repository — locating definitions, finding callers/call-graphs, tracing imports, estimating blast radius before edits, checking hot files, finding dead code — and before any risky write (dry-run impact, guard checks, checkpoints). Answers structural questions from the graph instead of reading files, saving thousands of tokens on large codebases.
---

# SMP — Structural Memory Protocol

SMP models the current repository as a structural graph: every function,
class, file and interface is a node; CALLS / IMPORTS / INHERITS / TESTS are
edges. It is served over MCP by `smp-mcp`, wired into most agent harnesses by
the SMP installer. Prefer graph queries over reading files.

## Golden rules

1. **Graph first, then files.** Before grepping or reading, ask the graph:
   `smp_locate` (keywords) → `smp_navigate` (entity + relationships) →
   `smp_code_snippet` (exact source).
2. **Impact before edit.** For any non-trivial change run `smp_impact`
   (change_type: `delete` / `signature_change` / `move`) and cite the blast
   radius in your plan.
3. **Write sessions for risky writes.** `smp_session_open` (write mode) →
   `smp_dryrun` → edit only if dryrun says `safe` → `smp_session_close`.
   Checkpoint first with `smp_checkpoint` when the change is deep.
4. **Keep the graph fresh.** After you create/edit/delete files in a repo
   that has a graph, push the changed file: `smp_update` with
   `file_path`, `content`, `change_type` (`created` / `modified` / `deleted`).

## Tool cheat sheet (all prefixed `smp_`)

Discovery
- `smp_locate(query, top_k)` — BM25 keyword search over names, docstrings,
  tags, paths; use for "where is X implemented" and feature discovery.
- `smp_architecture()` — high-level repo overview from the graph.
- `smp_file_outline(file_path)` — all symbols in one file, sized.
- `smp_context(file_path, scope)` — programmer's mental model per file:
  role, blast radius, risk level, heat score, tests coverage. Check **risk
  level and heat score before touching** a file.

Relationships
- `smp_trace(entity, relationship, direction, depth)` — who calls what, who
  is imported by which file; `direction: incoming|outgoing`.
- `smp_flow(start, end)` — data/control flow between two entities.
- `smp_why(entity)` — "why is this connected?" provenance in one call.
- `smp_dead_code(top_k)` — candid historical dead code.

Safe writes
- `smp_session_open(task, scope, mode)` — declare intent once per task.
- `smp_dryrun(file_path, proposed_content)` — pre-flight; verdict
  `safe|breaking` with affected callers + missing tests.
- `smp_checkpoint(session_id, files)` / `smp_rollback(session_id, checkpoint_id)`
- `smp_lock(session_id, files)` — stop concurrent agents from colliding.

Maintenance
- `smp_update(file_path, content, change_type)` — sync one file after edit.
- `smp_batch_update(changes)` — atomic multi-file sync.
- `smp_search_code(pattern)` — literal search through indexed code.

## Workflow recipes

Understand unfamiliar code
1. `smp_locate("keyword of the feature")` → pick the best `entity`.
2. `smp_navigate(entity)` → see definition + callers + callees.
3. `smp_code_snippet(entity)` → read source only of the exact code.

Plan a refactor
1. `smp_impact(entity|"file_path", change_type)` — blast radius.
2. `smp_context(file_path, "edit")` — risk level, tests coverage.
3. `smp_session_open(..., mode="write")` → `smp_checkpoint(...)` →
   `smp_dryrun(...)` → only then write. Close with
   `smp_session_close(session_id, "completed")`.

After edits
1. `smp_update(file_path, new_content, change_type="modified")`
2. `smp_enrich_stale(scope="full")` if enrichment is stale.

## Troubleshooting

- Tools return empty / "entity not found": the repo has no graph yet —
  the launcher auto-ingests on first use; if disabled
  (`SMP_AUTO_INGEST=0`), run `smp ingest .` (from the repo root) once.
- Large repo keeps re-ingesting: pin the graph explicitly with
  `SMP_GRAPH_PATH=/absolute/path/.smp/graph.smpg` in the server env.
- Same-named helpers may link to multiple callers (over-approximation by
  design): prefer `smp_trace` with namespaced `entity` paths, then
  `smp_code_snippet` to disambiguate before editing.
- JSON-RPC (no MCP): `POST http://localhost:8420/rpc` with
  `{"jsonrpc":"2.0","method":"smp/locate","params":{"query":"..."},"id":1}`
  after `smp serve --port 8420`.
