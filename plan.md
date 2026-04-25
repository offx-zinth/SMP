---
name: Enterprise SMP Roadmap
overview: Transform SMP from a strong local prototype into an enterprise-ready code intelligence platform by closing the gaps in persistence, security, distributed coordination, sandboxing, observability, scale, and release governance.
todos:
  - id: phase-1-persistence
    content: Implement durable mmap-backed graph storage and reopen tests.
    status: completed
  - id: phase-2-wal
    content: Implement WAL transactions, replay, checkpointing, and crash recovery tests.
    status: completed
  - id: phase-3-safety
    content: Persist sessions, locks, and audit logs with multi-agent conflict tests.
    status: completed
  - id: phase-4-security
    content: Add authentication, authorization scopes, request hardening, and safe error responses.
    status: completed
  - id: phase-5-integrations
    content: Replace sandbox and PR stubs with real isolated execution and Git provider adapters, or explicitly narrow product scope.
    status: completed
  - id: phase-6-ops
    content: Add observability, readiness checks, backup/restore, admin tooling, and runbooks.
    status: completed
  - id: phase-7-release
    content: Prove scale with benchmarks, wire vector search into the server, and enforce enterprise CI/release gates.
    status: in_progress
isProject: false
---

# Enterprise SMP Roadmap

## Current Readiness Summary

SMP has a clean JSON-RPC surface, useful graph/query semantics, parser integration, and broad protocol test coverage. It is not enterprise-ready yet because the default graph store is memory-first, sessions and locks are not durable, the API has no authentication or authorization, sandbox and PR workflows are mostly metadata stubs, and operational controls are not yet production-grade.

The critical path is: make data durable, make mutations safe, secure the API, then harden integrations and operations.

```mermaid
flowchart TD
    client[EnterpriseClient] --> api[FastAPI_JSON_RPC]
    api --> auth[Auth_And_Policy]
    auth --> graph[DurableGraphStore]
    graph --> wal[WAL_And_Recovery]
    graph --> vector[VectorStore]
    api --> locks[Sessions_And_Locks]
    api --> sandbox[SandboxBackend]
    api --> git[GitProviderAdapters]
    api --> obs[Telemetry_And_Audit]
```

## Phase 1: Persistence Foundation

Goal: make SMP data survive restart and match the storage promises in [SPEC.md](d:/nemotron/SPEC.md).

Key work:
- Rework [smp/store/graph/mmap_store.py](d:/nemotron/smp/store/graph/mmap_store.py) so nodes and edges are written through real mmap-backed stores, not only `_nodes`, `_edges`, and `_edge_index` dictionaries.
- Implement real serialization and offsets in [smp/store/graph/node_store.py](d:/nemotron/smp/store/graph/node_store.py), [smp/store/graph/edge_store.py](d:/nemotron/smp/store/graph/edge_store.py), [smp/store/graph/string_pool.py](d:/nemotron/smp/store/graph/string_pool.py), and [smp/store/graph/index.py](d:/nemotron/smp/store/graph/index.py).
- Load graph state from disk during `MMapGraphStore.connect()`.
- Add reopen tests: write graph, close process/store, reopen, query same nodes and edges.
- Define versioned file layout and migration hooks.

Acceptance criteria:
- Restart preserves nodes, edges, parse status, file manifest, and indexes.
- Basic graph CRUD no longer depends on process-only dictionaries as the source of truth.
- Tests prove persistence across close/reopen and corrupted-header handling.

## Phase 2: WAL, Transactions, and Recovery

Goal: make graph mutations crash-safe and consistent.

Key work:
- Finish WAL implementation in [smp/store/graph/mmap_file.py](d:/nemotron/smp/store/graph/mmap_file.py), including replay, commit records, checkpoint semantics, and corruption handling.
- Route all mutating operations through a transaction boundary: node upsert, edge upsert, delete, parse/import, enrichment, tags, annotations, sessions, and locks.
- Add configurable durability modes: `always_fsync`, `periodic_fsync`, and `best_effort`.
- Add crash-recovery tests that simulate partial writes, failed checkpoints, and replay after restart.
- Add integrity checks that validate root pointers, indexes, edge references, and orphaned records.

Acceptance criteria:
- A killed process can restart and recover to the last committed transaction.
- WAL replay is deterministic and idempotent.
- `smp/integrity/check` validates real on-disk invariants, not only in-memory state.

## Phase 3: Sessions, Locks, Audit, and Multi-Agent Safety

Goal: make SMP safe for multiple agents and enterprise workflows.

Key work:
- Replace no-op session and lock methods in [smp/store/graph/mmap_store.py](d:/nemotron/smp/store/graph/mmap_store.py) with durable implementations.
- Define lock lease semantics: owner, TTL, renew, release, fencing token, stale lock cleanup.
- Ensure [smp/protocol/handlers/session.py](d:/nemotron/smp/protocol/handlers/session.py) enforces real conflicts on the default store.
- Persist audit logs as append-only records with request ID, actor ID, method, affected resources, and outcome.
- Add concurrency tests for two agents editing the same file, stale lock expiry, session restart, and unlock failure.

Acceptance criteria:
- Two clients cannot acquire conflicting locks.
- Locks and sessions survive server restart or fail closed with clear recovery behavior.
- Audit records are durable and queryable.

## Phase 4: Enterprise Security Layer

Goal: make the API safe to expose inside an enterprise network.

Key work:
- Add authentication to [smp/protocol/server.py](d:/nemotron/smp/protocol/server.py): start with API keys or bearer tokens, with a path to OIDC or mTLS.
- Add authorization scopes per method: read, write, admin, sandbox, audit, and integration management.
- Protect `/rpc`, `/stats`, `/methods`, and `/smp/invalidate`; decide whether `/health` is public liveness only.
- Add request limits, body-size limits, timeout controls, and production-safe error responses.
- Add deployment guidance for TLS termination, reverse proxy, CORS, trusted hosts, and network policy.

Acceptance criteria:
- Unauthorized clients cannot read or mutate graph data.
- Dangerous methods require admin or write scopes.
- Server logs raw exceptions internally but returns stable, non-leaky JSON-RPC errors to clients.

## Phase 5: Real Sandbox and Git Provider Integrations

Goal: replace metadata-only workflows with real enterprise integrations.

Key work:
- Decide product boundary for [smp/protocol/handlers/sandbox.py](d:/nemotron/smp/protocol/handlers/sandbox.py): either implement real isolated execution or explicitly remove execution semantics.
- If implemented, use a hardened backend such as Docker with seccomp/resource limits, Firecracker, or a managed execution service.
- Add CPU, memory, disk, network, timeout, filesystem, and secret-access policies.
- Replace synthetic PR/review storage in [smp/protocol/handlers/review.py](d:/nemotron/smp/protocol/handlers/review.py) with adapters for GitHub, GitLab, or Azure DevOps.
- Support real PR creation, comments, status checks, webhooks, branch protection awareness, and CODEOWNERS-style reviewer policy.

Acceptance criteria:
- Sandbox execution is either truly isolated or not marketed as execution.
- PR creation creates real provider-side PRs and stores stable external IDs.
- Integration failures are retried or surfaced with actionable error states.

## Phase 6: Observability, Operations, and Admin Tooling

Goal: make SMP operable by platform teams.

Key work:
- Add OpenTelemetry traces and Prometheus metrics around JSON-RPC latency, error rate, graph mutations, WAL depth, replay time, parser queue depth, lock conflicts, sandbox runs, and provider calls.
- Split health into liveness and readiness: server alive, store open, WAL healthy, parser scheduler healthy, vector store healthy.
- Add backup and restore commands to [smp/cli.py](d:/nemotron/smp/cli.py), including validation after restore.
- Add admin commands for integrity check, compaction, migration, WAL replay dry-run, and index rebuild.
- Define runbooks for corruption, disk full, failed migration, stuck locks, and slow queries.

Acceptance criteria:
- Operators can monitor SLOs and diagnose failures without attaching a debugger.
- Backups can be restored and verified in CI.
- Health endpoints reflect real dependency status.

## Phase 7: Scale, Performance, and Release Hardening

Goal: prove SMP works at enterprise repository size and is safe to release.

Key work:
- Build benchmark suites for 100K, 1M, and 10M+ node graphs with realistic repositories.
- Add load tests for concurrent reads, writes, parser invalidation, lock contention, and semantic search.
- Wire [smp/vector/mmap_vector.py](d:/nemotron/smp/vector/mmap_vector.py) into the product server, then add approximate nearest-neighbor indexing or another scalable retrieval backend if linear scan becomes a bottleneck.
- Fix strict typing and CI drift: `ruff check .`, `ruff format --check .`, `mypy smp/`, full test suite, coverage threshold, dependency audit, and security scan.
- Package releases with signed artifacts, SBOM, changelog, migration notes, and compatibility matrix.

Acceptance criteria:
- CI is green from a clean checkout without ignored fixture failures.
- Published benchmarks show acceptable latency, memory, and recovery time for target enterprise repo sizes.
- Release artifacts are reproducible, signed, and documented.

## Enterprise Definition of Done

SMP can be considered enterprise-ready when:
- Data survives restart and crash recovery under tested failure modes.
- Authenticated clients are authorized per method and tenant or workspace.
- Sessions, locks, audit logs, and destructive operations are durable and enforceable.
- Sandbox and PR features either perform real work safely or are clearly scoped out.
- Operators have metrics, traces, readiness probes, backup/restore, and runbooks.
- CI enforces lint, formatting, typing, tests, coverage, and security checks.
- Performance is proven on repositories comparable to target customers.

## Suggested Milestone Order

Ship this as three larger business milestones:
- Milestone A: Durable single-node SMP: Phases 1–3.
- Milestone B: Secure enterprise beta: Phases 4 and 6 baseline.
- Milestone C: Production GA: Phases 5–7, including scale validation and release governance.