# SMP Enterprise Production Readiness Test Plan

## Overview

This plan defines a comprehensive testing strategy to validate SMP for enterprise production use. It covers functional testing, security validation, performance benchmarking, disaster recovery, and operational procedures.

**Scope:** All SMP components - Graph Store, Vector Store, API, CLI, Observability  
**Target:** Enterprise production deployment readiness  
**Duration:** ~3-4 days of testing effort

---

## Phase 1: Functional Verification

### 1.1 Core Graph Operations

| Test ID | Test Case | Success Criteria | Priority |
|---------|-----------|------------------|----------|
| F-001 | Node CRUD | Create, read, update, delete nodes succeeds | P0 |
| F-002 | Edge CRUD | Create, read, update, delete edges succeeds | P0 |
| F-003 | Batch node upsert | 10K nodes inserted in single transaction | P0 |
| F-004 | Batch edge upsert | 50K edges inserted in single transaction | P0 |
| F-005 | Cross-file references | Ingest 2 files with import relationship, verify edge | P0 |
| F-006 | Query by type | Query all function nodes returns correct results | P0 |
| F-007 | Query by name | Search by exact name returns correct node | P0 |
| F-008 | Traversal depth 5 | Navigate 5 levels deep returns expected subgraph | P0 |
| F-009 | Impact analysis | Deleting function shows all dependent nodes | P0 |
| F-010 | Session lifecycle | Begin, modify, checkpoint, rollback session | P1 |

### 1.2 JSON-RPC API

| Test ID | Test Case | Success Criteria | Priority |
|---------|-----------|------------------|----------|
| F-011 | All 52 handlers respond | Each handler returns valid JSON-RPC response | P0 |
| F-012 | Invalid JSON handling | Malformed JSON returns -32700 parse error | P0 |
| F-013 | Missing method handling | Unknown method returns -32601 method not found | P0 |
| F-014 | Missing params handling | Params default to empty dict `{}` | P0 |
| F-015 | Non-dict params handling | Non-dict params coerced to empty dict | P0 |
| F-016 | HTTP health endpoint | `GET /health` returns 200 with status | P0 |
| F-017 | HTTP stats endpoint | `GET /stats` returns node/edge counts | P1 |
| F-018 | HTTP methods endpoint | `GET /methods` lists all 52 handlers | P1 |
| F-019 | File invalidation | `POST /smp/invalidate` triggers reparse | P1 |

### 1.3 Vector Operations

| Test ID | Test Case | Success Criteria | Priority |
|---------|-----------|------------------|----------|
| F-020 | Vector upsert | Insert 1K vectors, verify count | P0 |
| F-021 | Vector query | Query by embedding returns nearest neighbors | P0 |
| F-022 | Vector delete | Delete vectors, verify removal | P0 |
| F-023 | Hybrid search | Combined vector + metadata filtering | P1 |
| F-024 | Bulk vector import | Import 10K vectors via index/import | P1 |

---

## Phase 2: Security Validation

### 2.1 Authentication & Authorization

| Test ID | Test Case | Success Criteria | Priority |
|---------|-----------|------------------|----------|
| S-001 | No auth by default | Request without API key returns 401 | P0 |
| S-002 | Valid API key accepted | Request with valid key succeeds | P0 |
| S-003 | Invalid API key rejected | Request with wrong key returns 401 | P0 |
| S-004 | Expired key rejected | Key with expired_at in past returns 401 | P0 |
| S-005 | Open mode disabled | Missing keys file does NOT enable open mode | P0 |
| S-006 | Open mode with env var | `SMP_OPEN_MODE=1` enables open mode | P0 |
| S-007 | Rate limiting active | >60 requests/min returns 429 | P0 |
| S-008 | Redis rate limit sync | 2 instances share rate limit via Redis | P0 |
| S-009 | Fallback rate limit | Redis down, in-memory rate limiting works | P0 |
| S-010 | Failed auth logging | Invalid token attempt logged with warning | P1 |

### 2.2 Input Validation

| Test ID | Test Case | Success Criteria | Priority |
|---------|-----------|------------------|----------|
| S-011 | Path traversal blocked | `../../etc/passwd` rejected with 400 | P0 |
| S-012 | Path allowlist enforced | Path outside `SMP_ALLOWED_PATHS` rejected | P0 |
| S-013 | Sandbox command whitelist | Command not in `SMP_SANDBOX_ALLOWED_COMMANDS` rejected | P0 |
| S-014 | Request size limit | Request >1MB rejected with 413 | P0 |
| S-015 | SQL injection prevention | SQL-like strings in queries handled safely | P1 |

### 2.3 Vulnerability Scanning

| Test ID | Test Case | Success Criteria | Priority |
|---------|-----------|------------------|----------|
| S-016 | pip-audit clean | `pip-audit` finds no vulnerabilities | P0 |
| S-017 | Dependency scan | All dependencies have no known CVEs | P0 |

---

## Phase 3: Performance & Scalability

### 3.1 Latency Benchmarks

| Test ID | Benchmark | Target | Priority |
|---------|-----------|--------|----------|
| P-001 | Single node upsert | p50 < 5ms | P0 |
| P-002 | Single edge upsert | p50 < 5ms | P0 |
| P-003 | Query navigation | p50 < 10ms, p99 < 50ms | P0 |
| P-004 | Vector query (1K vectors) | p50 < 5ms | P0 |
| P-005 | Vector query (100K vectors) | p50 < 20ms | P0 |
| P-006 | Depth-5 traversal (1K nodes) | p99 < 50ms | P0 |
| P-007 | Depth-5 traversal (100K nodes) | p99 < 100ms | P0 |
| P-008 | Batch insert (10K nodes) | Total time < 5s | P1 |

### 3.2 Throughput Benchmarks

| Test ID | Benchmark | Target | Priority |
|---------|-----------|--------|----------|
| P-009 | Concurrent reads (10 clients) | >500 req/s | P1 |
| P-010 | Concurrent writes (10 clients) | >200 req/s | P1 |
| P-011 | Mixed workload (80/20 read/write) | >400 req/s | P1 |

### 3.3 Scale Testing

| Test ID | Test Case | Success Criteria | Priority |
|---------|-----------|------------------|----------|
| P-012 | 1M nodes | Graph operations remain functional | P0 |
| P-013 | 10M edges | Traversal depth 5 p99 < 200ms | P0 |
| P-014 | 1M vectors | Vector query p50 < 50ms | P0 |
| P-015 | Large session | 1000 operations in single session | P1 |

---

## Phase 4: High Availability & Disaster Recovery

### 4.1 Crash Recovery

| Test ID | Test Case | Success Criteria | Priority |
|---------|-----------|------------------|----------|
| D-001 | Graceful shutdown | SIGTERM triggers clean shutdown, no data loss | P0 |
| D-002 | Hard crash recovery | Kill -9 during write, restart recovers data | P0 |
| D-003 | Journal replay | Restart replays uncommitted transactions | P0 |
| D-004 | Corrupted journal | Damaged journal entry skipped, remaining replay | P1 |
| D-005 | Vector store recovery | Vector store rebuilds from graph store | P1 |

### 4.2 Backup & Restore

| Test ID | Test Case | Success Criteria | Priority |
|---------|-----------|------------------|----------|
| D-006 | CLI backup | `smp backup` creates consistent snapshot | P0 |
| D-007 | CLI restore | `smp restore` recovers to exact state | P0 |
| D-008 | Incremental backup | Backup only new journal entries | P1 |
| D-009 | Cross-version restore | Backup from v1.x restores to v1.y | P1 |

### 4.3 Multi-Instance

| Test ID | Test Case | Success Criteria | Priority |
|---------|-----------|------------------|----------|
| D-010 | Two-instance failover | Instance 1 down, instance 2 serves requests | P1 |
| D-011 | Rate limit consistency | Both instances enforce same per-key limits | P0 |
| D-012 | Health check accuracy | `/health` reflects actual dependency status | P1 |

---

## Phase 5: Observability Validation

### 5.1 Logging

| Test ID | Test Case | Success Criteria | Priority |
|---------|-----------|------------------|----------|
| O-001 | Correlation ID propagation | All logs for request share same correlation_id | P0 |
| O-002 | Correlation ID in response | `X-Correlation-ID` header present in response | P0 |
| O-003 | Structured logging | All events include required fields (level, logger, timestamp) | P0 |
| O-004 | Auth failure logging | Failed auth attempts logged at WARNING | P1 |
| O-005 | Shutdown sequence logging | All 4 shutdown phases logged | P1 |

### 5.2 Metrics

| Test ID | Test Case | Success Criteria | Priority |
|---------|-----------|------------------|----------|
| O-006 | Prometheus endpoint | `GET /metrics` returns valid Prometheus format | P0 |
| O-007 | Request counter metric | Requests counted by method and status | P1 |
| O-008 | Latency histogram | Request duration histogram present | P1 |
| O-009 | Graph size metrics | Node/edge counts in metrics | P1 |

### 5.3 Alerting

| Test ID | Test Case | Success Criteria | Priority |
|---------|-----------|------------------|----------|
| O-010 | Alert rules valid | Prometheus rules pass validation | P0 |
| O-011 | Dashboard loads | Grafana dashboard renders all panels | P0 |
| O-012 | Error rate alert fires | Simulate 5% error rate, alert fires within 5m | P1 |
| O-013 | Latency alert fires | Simulate p99 > 2s, alert fires within 5m | P1 |

---

## Phase 6: Operational Procedures

### 6.1 Installation & Configuration

| Test ID | Test Case | Success Criteria | Priority |
|---------|-----------|------------------|----------|
| OP-001 | Fresh install | `pip install smp` completes without error | P0 |
| OP-002 | Configuration via env | All settings configurable via environment variables | P0 |
| OP-003 | Configuration validation | Invalid configuration produces clear error | P1 |
| OP-004 | Dependency compatibility | No conflicts with common enterprise packages | P1 |

### 6.2 CLI Commands

| Test ID | Test Case | Success Criteria | Priority |
|---------|-----------|------------------|----------|
| OP-005 | `smp serve` | Server starts and accepts requests | P0 |
| OP-006 | `smp ingest` | Directory ingested successfully | P0 |
| OP-007 | `smp backup` | Backup created with all components | P0 |
| OP-008 | `smp restore` | Data restored from backup | P0 |
| OP-009 | `smp compact` | Storage compacted, data intact | P1 |
| OP-010 | `smp integrity` | Integrity check passes | P0 |

### 6.3 Upgrade Procedures

| Test ID | Test Case | Success Criteria | Priority |
|---------|-----------|------------------|----------|
| OP-011 | Version compatibility | v1.x → v1.y data intact | P0 |
| OP-012 | Downgrade safety | Cannot restore newer backup to older version | P1 |
| OP-013 | Migration documentation | Runbook upgrade.md is accurate and complete | P1 |

---

## Phase 7: Compliance & Governance

### 7.1 Data Privacy

| Test ID | Test Case | Success Criteria | Priority |
|---------|-----------|------------------|----------|
| C-001 | Data at rest encryption | Graph store is not human-readable | P1 |
| C-002 | Audit trail | All data mutations logged with actor identity | P1 |
| C-003 | Data retention | Old data can be purged via retention policy | P1 |

### 7.2 Access Control

| Test ID | Test Case | Success Criteria | Priority |
|---------|-----------|------------------|----------|
| C-004 | Key rotation | API key can be rotated without downtime | P1 |
| C-005 | Scope enforcement | Read-only key cannot perform writes | P1 |
| C-006 | Audit logs | All admin actions logged | P1 |

---

## Test Execution Matrix

| Category | P0 Tests | P1 Tests | P2 Tests | Total |
|----------|----------|----------|----------|-------|
| Functional | 18 | 7 | 0 | 25 |
| Security | 10 | 5 | 0 | 15 |
| Performance | 8 | 5 | 0 | 13 |
| Disaster Recovery | 5 | 7 | 0 | 12 |
| Observability | 5 | 8 | 0 | 13 |
| Operations | 5 | 6 | 0 | 11 |
| Compliance | 0 | 6 | 0 | 6 |
| **Total** | **51** | **44** | **0** | **95** |

**P0:** Must pass for production deployment  
**P1:** Should pass; known issues documented  
**P2:** Nice to have

---

## Test Environment Requirements

### Hardware
- **CPU:** 8 cores minimum (16 recommended)
- **RAM:** 32GB minimum (64GB recommended)
- **Disk:** 100GB SSD minimum

### Software
- **Python:** 3.11+
- **Graph store:** self-contained mmap journal (`.smpg`, no external DB)
- **Vector store:** FAISS over mmap (`.smpv`, bring-your-own-embeddings)
- **Prometheus:** 2.x
- **Grafana:** 10.x

### Network
- Stable localhost connectivity for single-instance tests
- Network partition simulation capability for HA tests

---

## Bug Severity Definitions

| Severity | Definition | Test Impact |
|----------|------------|--------------|
| **P0 - Critical** | Data loss, security breach, complete outage | Must fix before release |
| **P1 - Major** | Major feature broken, workarounds exist | Should fix before release |
| **P2 - Minor** | Minor feature degraded, cosmetic issues | Fix in next release |
| **P3 - Low** | No functional impact, improvement | Backlog |

---

## Sign-Off Checklist

Before production deployment, verify:

- [ ] All P0 tests pass (51 tests)
- [ ] All P1 tests pass or waived with documented justification
- [ ] Performance benchmarks meet targets
- [ ] Security scan shows no critical vulnerabilities
- [ ] Runbooks are reviewed and approved
- [ ] On-call team trained on SMP operations
- [ ] Rollback procedure tested and documented
- [ ] Monitoring dashboards deployed and verified
- [ ] Alert routing tested (notifications received)
- [ ] Capacity planning completed with growth projections

---

## Schedule

| Day | Focus | Tests |
|-----|-------|-------|
| Day 1 | Functional + Security | F-001 to F-024, S-001 to S-017 |
| Day 2 | Performance + Scale | P-001 to P-015 |
| Day 3 | Disaster Recovery + Observability | D-001 to D-012, O-001 to O-013 |
| Day 4 | Operations + Compliance | OP-001 to OP-013, C-001 to C-006 |

---

*Document Version: 1.0*  
*Last Updated: 2026-04-27*  
*Owner: Platform Engineering Team*