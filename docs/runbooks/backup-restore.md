# Backup and Restore Runbook

## Overview

This runbook covers how to safely backup and restore the SMP (Structural Memory Protocol) graph store. SMP uses a durable append-only journal stored in a single `.smpg` file, plus an optional FAISS-backed vector store (`.smpv`) holding only caller-supplied embeddings.

The backup strategy ensures consistency even while the server is running by:
1. Flushing all pending writes to the operating system
2. Snapshotting the file at a known safe point
3. Copying only the bytes that represent a complete journal state

Restores require the server to be stopped to prevent data conflicts.

## Architecture

### Data Components

The SMP persistence layer consists of three main components:

1. **Graph Store** (`.smpg`)
   - Memory-mapped append-only journal
   - Contains all node, edge, session, lock, and audit records
   - Journal format: variable-length records prefixed with type and length
   - Can be safely copied while server is running

2. **Vector Store** (`.smpv`, default `.smp/smp.smpv`)
    - FAISS similarity index over caller-supplied embeddings (bring-your-own-embeddings)
    - Ingest creates no embeddings; populated only via `smp/vector/upsert`
    - Optional for keyword search operations (which never touch vectors)

3. **Configuration** (`.env`, `*.yaml`)
    - Environment variables (`SMP_GRAPH_PATH`, `SMP_VECTOR_PATH`) and tuning parameters
    - No external database credentials — both stores are self-contained local files

### File Structure

```
.smp/
├── graph.smpg           # Main journal (required)
├── smp.smpv             # Vector store (optional, caller-supplied embeddings only)
├── graph.smpg.bak.TIMESTAMP  # Restore sidecar
└── graph.smpg.precompact.TIMESTAMP  # Pre-compaction backup
```

## Backup Procedures

### CLI Backup (Recommended)

The safest way to backup is using the CLI, which coordinates with the journal layer:

```bash
# Basic backup (writes a gzipped tarball: graph snapshot + manifest.json)
python3.11 -m smp.cli backup \
  --graph-path /path/to/graph.smpg \
  --output /backups/graph-$(date +%Y%m%d-%H%M%S).tar.gz

# Output
# Backup written: /backups/graph-20250427-143022.tar.gz (12345678 bytes)
```

**How it works:**
1. Connects to the graph store
2. Flushes all pending journal writes to disk
3. Captures a consistent prefix of the live file (always a valid graph by construction)
4. Packs the snapshot plus a `manifest.json` (checksums, version metadata) into a `.tar.gz`
5. Creates backup atomically (temp file → rename)

**Advantages:**
- ✅ Works while server is running
- ✅ Guarantees consistency (doesn't include partial records)
- ✅ Can target any path (local, NFS, cloud storage)
- ✅ Atomic operation (no intermediate states)

### HTTP API Backup

For production integrations, use the `/admin/backup` endpoint:

```bash
# Requires ADMIN scope
curl -X POST http://localhost:8420/admin/backup \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target": "/backups/graph-backup.tar.gz"}'

# Response
# {
#   "backed_up_to": "/backups/graph-backup.tar.gz",
#   "bytes": 12345678
# }
```

**Requirements:**
- ADMIN scope in auth token
- Target path writable by SMP process
- Network connectivity to target filesystem

### Automated Backup Strategy

#### Daily Backups with Retention

Create a cron job for daily backups:

```bash
#!/bin/bash
# /usr/local/bin/smp-backup-daily.sh

BACKUP_DIR=/backups/smp
RETENTION_DAYS=30
GRAPH_PATH=${SMP_GRAPH_PATH:-.smp/graph.smpg}

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Generate timestamped backup (gzipped tarball: snapshot + manifest.json)
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="$BACKUP_DIR/graph-$TIMESTAMP.tar.gz"

python3.11 -m smp.cli backup \
  --graph-path "$GRAPH_PATH" \
  --output "$BACKUP_FILE"

if [ $? -eq 0 ]; then
  echo "✓ Backup successful: $BACKUP_FILE"
  
  # Cleanup old backups (keep last 30 days)
  find "$BACKUP_DIR" -name "graph-*.tar.gz" -mtime +$RETENTION_DAYS -delete
  echo "✓ Cleanup complete (removed files older than $RETENTION_DAYS days)"
else
  echo "✗ Backup failed!"
  exit 1
fi
```

Schedule with cron:

```crontab
# Daily backup at 2 AM UTC
0 2 * * * /usr/local/bin/smp-backup-daily.sh >> /var/log/smp-backup.log 2>&1
```

#### Backup Verification

Always verify backups after creation:

```bash
# Check the tarball is well-formed and contains snapshot + manifest
tar -tzf /backups/graph-latest.tar.gz
# graph.smpg
# manifest.json

# Verify live store integrity (requires graph path, not the tarball)
python3.11 -m smp.cli integrity --graph-path .smp/graph.smpg
```

## Restore Procedures

### Pre-Restore Checklist

Before restoring:

- [ ] **Stop the SMP server** — no restore while running
- [ ] **Verify backup file** — file exists and is readable
- [ ] **Document current state** — record what's being replaced
- [ ] **Test on staging** — always test restore on non-production first
- [ ] **Have rollback plan** — keep previous backup accessible

### CLI Restore (Recommended)

```bash
# 1. Stop the server
sudo systemctl stop smp-server

# 2. Restore from backup (creates .bak sidecar of current state)
python3.11 -m smp.cli restore \
  --graph-path /path/to/graph.smpg \
  --input /backups/graph-20250427-143022.tar.gz

# Output
# Restored to: /path/to/graph.smpg
# Sidecar backup: /path/to/graph.smpg.bak.20250427T143530Z

# 3. Restart the server
sudo systemctl start smp-server

# 4. Verify restored state
curl http://localhost:8420/ready
# {"status": "ready"}
```

**How it works:**
1. Stores original file as timestamped `.bak` sidecar
2. Atomically replaces target with backup
3. Returns path and sidecar location
4. Server must replay journal on next startup

### Restore with Verification

For production restores, add verification:

```bash
#!/bin/bash
RESTORE_FILE=$1
TARGET=${SMP_GRAPH_PATH:-.smp/graph.smpg}

# Stop server
sudo systemctl stop smp-server
sleep 2

# Create additional backup of current state
cp "$TARGET" "${TARGET}.backup.prestore.$(date +%s)"

# Restore
python3.11 -m smp.cli restore \
  --graph-path "$TARGET" \
  --input "$RESTORE_FILE"

# Restart and wait for journal replay
sudo systemctl start smp-server
sleep 5

# Verify connectivity
if curl -f http://localhost:8420/ready > /dev/null 2>&1; then
  echo "✓ Restore verified - server is ready"
  exit 0
else
  echo "✗ Verification failed - rolling back!"
  sudo systemctl stop smp-server
  # Sidecar is at ${TARGET}.bak.* - manually restore if needed
  exit 1
fi
```

### Point-in-Time Recovery

To recover to a specific point in time:

1. **List available backups**
   ```bash
   ls -lh /backups/graph-*.tar.gz | tail -20
   ```

2. **Select closest earlier backup**
   ```bash
   BACKUP="/backups/graph-20250420-020000.tar.gz"
   ```

3. **Follow CLI Restore steps above**

4. **For queries lost between backup and now:**
   - If you have WAL logs or audit trail, replay from there
   - Use `/audit/get` endpoint to review transaction history
   - Contact data engineering for point-recovery assistance

## Compaction

Over time, the journal accumulates redundant records (updates, deletes, overwrites). Compaction rewrites the journal containing only the current state.

### When to Compact

- Journal size exceeds 1 GB
- After bulk deletes
- During scheduled maintenance windows
- As part of capacity planning

### CLI Compaction

```bash
# Compact the journal
python3.11 -m smp.cli compact --graph-path /path/to/graph.smpg

# Output
# Compacted: 1234567890 -> 567890123 bytes (saved 666676767)
```

**Process:**
1. Creates fresh journal in-memory from current state
2. Writes to temporary `.compact` file
3. Backs up original as `.precompact.TIMESTAMP`
4. Atomically replaces original
5. Reopens store pointing at new file

### HTTP API Compaction

```bash
curl -X POST http://localhost:8420/admin/compact \
  -H "Authorization: Bearer $TOKEN"

# Response
# {
#   "compacted": true,
#   "before_bytes": 1234567890,
#   "after_bytes": 567890123
# }
```

## Vector Store Management

The vector store (`.smpv`) holds only caller-supplied embeddings for `smp/vector/*` similarity search.
Keyword search (`smp/search`, `smp/locate`) never uses it.

### Backup Vector Store

Vector store is included in filesystem snapshots but not CLI backup (re-supply embeddings via `smp/vector/upsert`
if lost):

```bash
# Backup graph backup tarball + vector store
tar -tzf backup-$(date +%Y%m%d).tar.gz  # inspect: graph snapshot + manifest.json
tar -czf vec-backup-$(date +%Y%m%d).tar.gz \
  /path/to/smp.smpv
```

### Restore Vector Store

If the vector store becomes corrupted, delete it and re-supply embeddings (ingest does not create any):

```bash
# Re-register a directory with the live watcher via JSON-RPC (server running)
curl -X POST http://localhost:8420/rpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "smp/reindex", "params": {"scope": "/path/to/project"}, "id": 1}'

# Then re-upsert your embeddings via smp/vector/upsert
```

## Disaster Recovery

### Corruption Recovery

If the graph file is corrupted:

1. **Run integrity check**
   ```bash
   python3.11 -m smp.cli integrity --graph-path /path/to/graph.smpg
   ```

2. **Review report**
   - Check `ok` field and detailed errors
   - Determine if partial or complete recovery possible

3. **Restore from backup**
   - Follow "Restore Procedures" above
   - Use most recent healthy backup

4. **Post-Mortem**
   - Enable enhanced durability (`PERIODIC` or `SYNC`)
   - Review hardware health (disk errors, memory errors)
   - Increase backup frequency

### Data Loss Recovery

**Scenario:** Server crashed, corrupted on-disk file, recent backup is stale.

**Recovery steps:**
1. Determine what data was lost (calculate time gap)
2. Restore from backup
3. Replay audit trail if available
4. Reconstruct via re-ingestion if possible

**Prevention:**
- Use `SYNC` durability mode for critical systems
- Maintain hourly backups for 24-hour retention
- Monitor disk I/O errors (`smartctl`, CloudWatch)
- Implement write-ahead logging (Phase 2)

## Configuration

### Environment Variables

```bash
# Graph file location
export SMP_GRAPH_PATH=.smp/graph.smpg

# Durability mode: best_effort (default), periodic, sync
export SMP_DURABILITY=periodic

# Flush frequency (writes before fsync)
export SMP_FLUSH_EVERY=64
```

### Durability Modes

| Mode | Guarantee | Performance | Use Case |
|------|-----------|-------------|----------|
| `BEST_EFFORT` | On crash loss possible | Fastest | Dev, testing |
| `PERIODIC` | Flush every N writes | Good throughput | Production |
| `SYNC` | Fsync every write | Slower | Critical systems |

## Monitoring

### Health Checks

```bash
# Liveness probe (always succeeds if process running)
curl http://localhost:8420/health
# {"status": "ok"}

# Readiness probe (checks graph store)
curl http://localhost:8420/ready
# {"status": "ready"}

# Detailed health check (dependencies)
curl http://localhost:8420/health/detailed
# {
#   "status": "healthy",
#   "checks": {
#     "graph_store": {"status": "accessible", "latency_ms": 1.2},
#     "vector_store": {"status": "accessible", "latency_ms": 0.8},
#     "journal": {"status": "healthy", "data_end": 1234567890}
#   }
# }
```

### Metrics

Monitor these metrics:

```promql
# Journal size (bytes)
smp_journal_size_bytes

# Graph cardinality
smp_nodes_total
smp_edges_total

# Active sessions/locks
smp_sessions_active
smp_locks_active
```

## Troubleshooting

### Backup Fails

**Error: "Device or resource busy"**
- Vector store still open? Ensure all clients closed
- Solution: Retry after 30 seconds

**Error: "No space left on device"**
- Target filesystem full
- Solution: Cleanup old backups, use different mount

### Restore Fails

**Error: "Backup file not found"**
- Path typo or permissions issue
- Solution: Verify path and file permissions

**Error: "Store locked by another process"**
- Server still running
- Solution: Stop server first (`systemctl stop smp-server`)

### Performance Issues After Restore

**Symptom: Queries slow after restore**
- Vector store (`.smpv`) not restored alongside the graph
- Solution: Restore the `.smpv` file from its own snapshot and re-upsert any missing embeddings via `smp/vector/upsert`

## Appendix: Journal Format

The journal format is:

```
[Header: 4096 bytes]
  - Magic: "SMPG" (4 bytes)
  - Version: 1 (4 bytes)
  - data_region_end (8 bytes)
  - reserved (4080 bytes)

[Data Region: variable]
  - [Record]*
    - type: uint8 (0=node, 1=edge, 2=session, 3=lock, 4=audit, 5=file)
    - length: uint32
    - payload: [length] bytes
```

Each record is self-describing and can be skipped by readers that don't understand its type.

## References

- Architecture: `ARCHITECTURE.md`
- API: `API.md`
- Settings: `smp/core/config.py`
