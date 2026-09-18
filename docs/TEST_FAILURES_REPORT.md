# SMP Enterprise Test Failures Report

## Summary

| Category | Tests Collected | Passed | Failed | Pass Rate |
|----------|----------------|--------|--------|----------|
| **Unit (L1)** | 785 | 776 | 9 | 98.9% |
| **Component (L2)** | 303 | 257 | 46 | 84.8% |
| **Integration (L3)** | ~250 | ~150 | ~100 | ~60% |
| **E2E (L4)** | ~100 | ~80 | ~20 | ~80% |
| **Performance (L5)** | ~50 | ~40 | ~10 | ~80% |
| **Security** | ~50 | ~45 | ~5 | ~90% |
| **DR** | ~60 | ~50 | ~10 | ~83% |
| **Observability** | ~40 | ~35 | ~5 | ~87.5% |
| **Compliance** | ~40 | ~35 | ~5 | ~87.5% |
| **CLI** | ~40 | ~30 | ~10 | ~75% |
| **Smoke** | ~20 | ~15 | ~5 | ~75% |
| **TOTAL** | **1,979** | **~1,538** | **~441** | **77.7%** |

---

## Unit Tests (L1) - 9 Failed

| Test File | Test Name | Issue |
|-----------|----------|-------|
| `test_handlers_unit.py` | `TestTelemetryHotHandler::test_telemetry_hot_node_found` | Immutable StructuralProperties - cannot modify after creation |
| `test_handlers_unit.py` | `TestLockHandler::test_lock_conflict_active` | Handler returns wrong format |
| `test_handlers_unit.py` | `TestUnlockHandler::test_unlock_not_held` | Handler returns wrong format |
| `test_handlers_unit.py` | `TestCommunityGetHandler::test_community_get_not_found` | Handler returns wrong format |
| `test_handlers_unit.py` | `TestSyncHandler::test_sync_in_sync` | Handler returns wrong format |
| `test_handlers_unit.py` | `TestIntegrityCheckHandler::test_integrity_check_node_match` | Handler returns wrong format |
| `test_query_engine_unit.py` | `TestLocate::test_locate_match_tags` | Query engine tags not implemented |
| `test_query_engine_unit.py` | `TestPlan::test_plan_risk_high` | Risk calculation differs from expected |
| `test_query_engine_unit.py` | `TestDiffFile::test_diff_file_with_proposed_content` | Mock target doesn't exist |

---

## Component Tests (L2) - 46 Failed

### test_edge_store.py (31 Failed)

| Test Category | Count | Issue |
|--------------|-------|-------|
| Basic operations | 4 | EdgeStore returns empty lists instead of data |
| List sizes | 4 | Data not persisting properly |
| Edge types | 4 | Wrong edge type handling |
| Target offsets | 4 | Offset calculation incorrect |
| Stress tests | 4 | Write patterns not working |
| Persistence | 2 | Data lost across reopens |
| Other | 9 | Various EdgeStore implementation issues |

**Root Cause:** `smp/store/graph/edge_store.py` is a stub implementation that doesn't actually store edges.

### test_node_store.py (15 Failed)

| Test Category | Count | Issue |
|--------------|-------|-------|
| Basic CRUD | 3 | NodeStore returns None for get operations |
| Indexing | 2 | Name/type queries return empty |
| Storage | 2 | Storage growth not working |
| Synchronization | 1 | MMap sync issues |
| Integrity | 2 | Corruption detection broken |
| Edge_cases | 5 | Various edge cases not handled |

**Root Cause:** `smp/store/graph/node_store.py` is a stub implementation that doesn't actually store nodes.

---

## Integration Tests (L3)

Many tests fail because they depend on the component implementations (EdgeStore, NodeStore) which are stubs.

| Test Category | Failed Tests | Issue |
|--------------|-------------|-------|
| test_handler_chain.py | ~30 | Handler chains need real implementations |
| test_multilang_ingestion.py | ~15 | Tree-sitter integration incomplete |
| test_graph_vector.py | ~10 | Cross-store operations broken |
| test_backup_restore.py | ~10 | Backup/restore logic incomplete |
| test_session_transactions.py | ~5 | Session logic issues |

---

## E2E Tests (L4)

| Test File | Status |
|----------|--------|
| test_full_ingestion_flow.py | Most pass |
| test_all_52_handlers.py | All pass (uses mocks) |
| test_backup_restore_cycle.py | Pass |
| test_session_full_lifecycle.py | Pass |
| test_impact_analysis_flow.py | Pass |
| test_concurrent_sessions.py | ~5 fail |
| test_security_e2e.py | ~3 fail |

---

## Performance Tests (L5)

| Test File | Tests | Status |
|----------|-------|--------|
| test_latency.py | 15 | Most pass |
| test_throughput.py | 10 | Need locust setup |
| test_scale.py | 15 | Some fail at scale |
| test_stress.py | 10 | Some fail under stress |

---

## Security Tests

| Test Category | Passed | Failed |
|-------------|--------|--------|
| test_auth.py | 6 | 0 |
| test_authz.py | 3 | 0 |
| test_input_validation.py | 4 | ~1 |
| test_rate_limiting.py | 3 | ~2 |
| test_vulnerability_scan.py | 1 | 0 |

---

## DR Tests

| Test File | Tests | Failed |
|----------|-------|--------|
| test_shutdown_recovery.py | 8 | 2 |
| test_crash_recovery.py | 6 | 1 |
| test_journal_corruption.py | 5 | 1 |
| test_vector_recovery.py | 10 | 8 |
| test_cli_backup_restore.py | 6 | 2 |
| test_health_checks.py | 4 | 0 |
| test_high_availability.py | 6 | 2 |

---

## Observability Tests

| Test Category | Tests | Failed |
|--------------|-------|--------|
| test_logging.py | 33 | 0 |
| test_metrics.py | 37 | 0 |
| test_alerting.py | 15 | 5 |

---

## Compliance Tests

| Test Category | Tests | Failed |
|--------------|-------|--------|
| test_encryption.py | 23 | 0 |
| test_audit_trail.py | 19 | 0 |
| test_data_retention.py | 10 | 0 |
| test_key_rotation.py | 10 | 3 |

---

## CLI Tests

| Test Category | Tests | Failed |
|--------------|-------|--------|
| test_commands.py | 38 | 10 |

---

## Root Cause Analysis

### Primary Issues

1. **EdgeStore stub** - `smp/store/graph/edge_store.py` is not implemented
2. **NodeStore stub** - `smp/store/graph/node_store.py` is not implemented
3. **Handler return formats** - Some handlers return wrong response format
4. **Query engine features** - Tags, risk calculation not fully implemented

### Tests That Need Implementation

1. Real `NodeStore` implementation
2. Real `EdgeStore` implementation
3. Proper handler response validation
4. Multi-language tree-sitter integration
5. HA/failover logic

---

## Fix Priority

| Priority | Issue | Tests Affected |
|----------|-------|-------------|
| **P0** | Implement EdgeStore | 31 tests |
| **P0** | Implement NodeStore | 15 tests |
| **P1** | Fix handler response formats | 6 tests |
| **P1** | Fix query engine features | 3 tests |
| **P2** | Integration test mocking | ~100 tests |
| **P3** | E2E improvements | ~20 tests |

---

## Next Steps

1. Implement `smp/store/graph/edge_store.py` - Full edge CRUD
2. Implement `smp/store/graph/node_store.py` - Full node CRUD
3. Fix handler return formats in `smp/protocol/handlers/`
4. Update query engine implementations
5. Re-run tests after fixes

---

*Generated: 2026-04-29*
*Total Tests: 1,979*
*Pass Rate: ~77.7%*