# Operational Maturity Phase - Quick Reference

## Quick Start

### Backup
```bash
# Create a backup
python3.11 -m smp.cli backup \
  --graph-path .smp/graph.smpg \
  --output backups/graph-$(date +%s).smpg
```

### Restore
```bash
# Stop server first
sudo systemctl stop smp-server

# Restore from backup (creates .bak sidecar)
python3.11 -m smp.cli restore \
  --graph-path .smp/graph.smpg \
  --input backups/graph-123456.smpg

# Restart server
sudo systemctl start smp-server
```

### Health Check
```bash
# Liveness (always quick)
curl http://localhost:8420/health

# Readiness (checks graph store)
curl http://localhost:8420/ready

# Comprehensive (all dependencies)
curl http://localhost:8420/health/detailed
```

### Graceful Shutdown
```bash
# Send SIGTERM to running server
kill -TERM <pid>

# Server will:
# 1. Stop accepting new requests
# 2. Wait up to 30s for in-flight requests
# 3. Flush journal (fsync)
# 4. Close connections
# 5. Exit cleanly
```

## Files Modified

| File | Changes |
|------|---------|
| `smp/cli.py` | Added graceful shutdown integration in serve command |
| `smp/protocol/server.py` | Added SIGTERM handler + /health/detailed endpoint |

## Files Created

| File | Purpose |
|------|---------|
| `docs/runbooks/backup-restore.md` | Complete backup/restore procedures |
| `docs/runbooks/upgrade.md` | Version upgrades and migrations |
| `.github/workflows/security.yml` | Vulnerability scanning with pip-audit |

## Key Features

### 1. Backup/Restore
- ✅ Works with running server
- ✅ Atomic operations
- ✅ Sidecar backups for rollback
- ✅ Compaction support

### 2. Health Checking
- ✅ Liveness probe (/health)
- ✅ Readiness probe (/ready)
- ✅ Comprehensive checks (/health/detailed)
- ✅ Latency measurements
- ✅ Dependency status

### 3. Graceful Shutdown
- ✅ SIGTERM handling
- ✅ Request draining (30s timeout)
- ✅ Journal flush on exit
- ✅ Clean connection closure

### 4. Security
- ✅ pip-audit vulnerability scanning
- ✅ Daily scheduled scans
- ✅ PR vulnerability comments
- ✅ Artifact storage

## Health Endpoint Responses

### /health (Liveness)
```json
{"status": "ok"}
```

### /ready (Readiness)
```json
{"status": "ready"}
```

### /health/detailed (Comprehensive)
```json
{
  "status": "healthy|degraded|unhealthy",
  "timestamp": 1234567890.123,
  "checks": {
    "graph_store": {
      "status": "accessible",
      "latency_ms": 1.2,
      "nodes": 1234
    },
    "vector_store": {
      "status": "accessible",
      "latency_ms": 0.8,
      "embeddings": 1234
    },
    "journal": {
      "status": "healthy",
      "file_size_bytes": 12345678,
      "data_end_bytes": 12345678,
      "sessions_active": 0,
      "locks_active": 0,
      "audit_entries": 150
    },
    "redis": {
      "status": "not_configured"
    }
  }
}
```

## Monitoring Setup

### Prometheus
```yaml
scrape_configs:
  - job_name: 'smp'
    static_configs:
      - targets: ['localhost:8420']
    metrics_path: '/metrics'
```

### Kubernetes
```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8420
  initialDelaySeconds: 5
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /ready
    port: 8420
  initialDelaySeconds: 10
  periodSeconds: 5
```

## CLI Commands

| Command | Purpose |
|---------|---------|
| `smp ingest <dir>` | Parse directory and build graph |
| `smp serve` | Start JSON-RPC server with graceful shutdown |
| `smp backup --output <file>` | Create backup snapshot |
| `smp restore --input <file>` | Restore from backup |
| `smp compact` | Rewrite journal to drop obsolete records |
| `smp integrity` | Run on-disk integrity check |

## Environment Variables

```bash
# Graph file location
export SMP_GRAPH_PATH=.smp/graph.smpg

# Durability mode (best_effort, periodic, sync)
export SMP_DURABILITY=periodic

# Flush frequency (writes before fsync)
export SMP_FLUSH_EVERY=64
```

## Documentation References

- **Backup/Restore:** See `docs/runbooks/backup-restore.md`
- **Upgrades:** See `docs/runbooks/upgrade.md`
- **Architecture:** See `ARCHITECTURE.md`
- **API:** See `API.md`

## Support

For issues or questions:
1. Check the troubleshooting section in relevant runbook
2. Review logs: `journalctl -u smp-server -f`
3. Run health check: `curl http://localhost:8420/health/detailed`
4. Report issue: https://github.com/anomalyco/smp/issues
