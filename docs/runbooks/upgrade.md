# Upgrade Runbook

## Overview

This runbook covers how to upgrade SMP (Structural Memory Protocol) to a new version while preserving data and maintaining service continuity. SMP is designed to maintain backward compatibility across versions for on-disk formats.

## Version Compatibility Matrix

| SMP Version | Python | Graph Format | Vector Store | Breaking Changes | Notes |
|-------------|--------|--------------|--------------|------------------|-------|
| 3.0.x       | 3.11+  | v1 (current) | FAISS `.smpv` (BYO embeddings) | None             | Latest stable |
| 2.5.x       | 3.10+  | v1           | FAISS `.smpv` (BYO embeddings) | Handler API      | EOL: 2025-12-31 |
| 2.4.x       | 3.9+   | v1           | FAISS `.smpv` (BYO embeddings) | Session tracking | EOL: 2025-06-30 |
| 2.3.x       | 3.9+   | v1 (initial) | None (added v2.4) | - | EOL: 2025-03-31 |

### Upgrade Paths

- **3.0.x ← 2.5.x**: Direct, data compatible
- **3.0.x ← 2.4.x**: Direct, requires handler registration
- **3.0.x ← 2.3.x**: Direct (vector store auto-created on first insert)
- **2.5.x ← 2.4.x**: Direct, all features compatible
- **2.4.x ← 2.3.x**: Minor compatibility (add session tracking)

### End-of-Life Schedule

- **3.0.x**: Security patches until 2027-01-01
- **2.5.x**: Bug fixes until 2025-12-31
- **2.4.x**: Critical only until 2025-06-30
- **2.3.x**: No support (please upgrade)

## Pre-Upgrade Checklist

- [ ] **Read release notes** — check for breaking changes
- [ ] **Verify Python version** — target version requires Python 3.11+
- [ ] **Backup current state** — create restore point
- [ ] **Test on staging** — always upgrade staging first
- [ ] **Schedule maintenance window** — plan downtime if needed
- [ ] **Notify users** — communicate service window
- [ ] **Review metrics baseline** — know current performance
- [ ] **Prepare rollback plan** — keep previous version available

## Upgrade Procedures

### Zero-Downtime Upgrade (3.0.x → 3.0.x patch)

For patch version upgrades (3.0.1 → 3.0.2), data format unchanged:

```bash
# 1. Install new version (no service restart needed yet)
pip install --upgrade smp==3.0.2

# 2. Gracefully signal server to reload handlers
# (server stays online accepting requests)
curl -X POST http://localhost:8420/admin/reload-handlers \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Response waits for in-flight requests to complete
# {"reloaded": true, "requests_completed": 142}
```

**Requirements:**
- Same major.minor version
- No database format changes
- No dependency version changes

### Standard Upgrade (Minor/Major)

For version upgrades with potential format changes:

```bash
#!/bin/bash
set -e

VERSION="3.0.0"
GRAPH_PATH=".smp/graph.smpg"
BACKUP_DIR="./backups"

echo "=== SMP Upgrade to $VERSION ==="

# 1. Create backup of current state (gzipped tarball: snapshot + manifest.json)
echo "Creating backup..."
mkdir -p "$BACKUP_DIR"
python3.11 -m smp.cli backup \
  --graph-path "$GRAPH_PATH" \
  --output "$BACKUP_DIR/pre-upgrade-$(date +%s).tar.gz"

# 2. Stop server
echo "Stopping server..."
sudo systemctl stop smp-server
sleep 2

# 3. Install new version
echo "Installing SMP $VERSION..."
pip install --upgrade "smp==$VERSION"

# 4. Verify integrity (no migrate step — the .smpg journal format is stable across these versions)
echo "Verifying integrity..."
python3.11 -m smp.cli integrity --graph-path "$GRAPH_PATH"

# 6. Restart server
echo "Starting server..."
sudo systemctl start smp-server
sleep 5

# 7. Health check
if curl -f http://localhost:8420/ready > /dev/null 2>&1; then
  echo "✓ Upgrade complete and verified"
  exit 0
else
  echo "✗ Health check failed - rolling back!"
  sudo systemctl stop smp-server
  exit 1
fi
```

### Blue-Green Deployment

For production environments, use blue-green deployment:

```bash
#!/bin/bash

CURRENT_VERSION="3.0.0"
NEW_VERSION="3.1.0"

BLUE_PORT=8420
GREEN_PORT=8421
BLUE_GRAPH=".smp/graph-blue.smpg"
GREEN_GRAPH=".smp/graph-green.smpg"

echo "=== Blue-Green Upgrade ==="

# 1. Copy current graph to green environment
echo "Setting up green environment..."
cp "$BLUE_GRAPH" "$GREEN_GRAPH"

# 2. Start new version on different port
echo "Starting SMP $NEW_VERSION on port $GREEN_PORT..."
python3.11 -m smp.cli serve \
  --port $GREEN_PORT \
  --graph-path "$GREEN_GRAPH" &
GREEN_PID=$!
sleep 3

# 3. Verify green is ready
echo "Verifying green health..."
if ! curl -f http://localhost:$GREEN_PORT/ready > /dev/null 2>&1; then
  kill $GREEN_PID
  echo "✗ Green environment failed to start"
  exit 1
fi

# 4. Switch load balancer / DNS to green
echo "Switching traffic to green..."
# Update your load balancer / proxy configuration
# Example: update Nginx upstream
# curl -X POST http://localhost:9090/api/reload-upstream \
#   -H "Content-Type: application/json" \
#   -d '{"upstream": "smp", "servers": [{"addr": "localhost:8421"}]}'

# 5. Monitor green for errors
echo "Monitoring green (30s)..."
for i in {1..30}; do
  if curl -f http://localhost:$GREEN_PORT/health > /dev/null 2>&1; then
    sleep 1
  else
    echo "✗ Green failed - switching back to blue..."
    # Revert upstream to blue
    exit 1
  fi
done

# 6. Decommission blue
echo "Decommissioning blue..."
sudo systemctl stop smp-server  # Blue
sleep 2
cp "$GREEN_GRAPH" "$BLUE_GRAPH"  # Promote green to blue

echo "✓ Upgrade complete - $NEW_VERSION is now live"
```

## Migration Guide by Version

### 2.3.x → 3.0.x

**Breaking changes:**
- Handler registration moved to `__init__.py`
- Session tracking now persistent (was ephemeral)
- Vector store holds caller-supplied embeddings only (ingest never generates embeddings)

**Upgrade steps:**
```bash
# 1. Backup (2.3.x format is compatible)
python3.11 -m smp.cli backup --output backup-2.3.tar.gz

# 2. Stop server and upgrade
sudo systemctl stop smp-server
pip install 'smp>=3.0.0'

# 3. No explicit migration needed - formats compatible
python3.11 -m smp.cli integrity

# 4. Restart
sudo systemctl start smp-server

# 5. Re-supply vector embeddings if you use smp/vector/* (vectors are caller-provided, never auto-populated)
```

### 2.4.x → 3.0.x

**Breaking changes:**
- Handler API stabilized (no changes)
- Query operators enhanced (backward compatible)
- RPC error codes standardized

**Upgrade steps:**
```bash
# 1. Backup and stop
python3.11 -m smp.cli backup --output backup-2.4.tar.gz
sudo systemctl stop smp-server

# 2. Upgrade
pip install 'smp>=3.0.0'

# 3. Verify and restart
python3.11 -m smp.cli integrity
sudo systemctl start smp-server
```

### 2.5.x → 3.0.x

**No breaking changes** - fully compatible

**Upgrade steps:**
```bash
# Simple in-place upgrade
pip install 'smp>=3.0.0'
systemctl restart smp-server
```

## Rollback Procedures

### If Upgrade Fails

```bash
#!/bin/bash

PREVIOUS_BACKUP="./backups/pre-upgrade-1234567890.tar.gz"
GRAPH_PATH=".smp/graph.smpg"

echo "=== Rollback Procedure ==="

# 1. Stop new version
sudo systemctl stop smp-server
sleep 2

# 2. Restore previous data
echo "Restoring from backup..."
python3.11 -m smp.cli restore \
  --graph-path "$GRAPH_PATH" \
  --input "$PREVIOUS_BACKUP"

# 3. Downgrade package
echo "Reverting to previous version..."
pip install 'smp==2.5.0'  # or current working version

# 4. Verify and restart
python3.11 -m smp.cli integrity --graph-path "$GRAPH_PATH"
sudo systemctl start smp-server

# 5. Monitor
sleep 5
curl http://localhost:8420/ready
```

### Fast Fallback (Blue-Green)

If using blue-green:

```bash
# Just revert DNS/load balancer to blue port
# Restore of data only needed if green was modified
```

## Performance Validation

After upgrade, validate performance:

```bash
# Compare metrics before and after
promtool query range \
  'smp_rpc_duration_seconds' \
  --start='2025-04-20T00:00:00Z' \
  --end='2025-04-27T00:00:00Z' \
  --step=1h

# Should see similar P99 latencies as before
# If degraded, investigate:
# - log.error() messages in smp-server logs
# - Vector store rebuild in progress? (check CPU)
# - Compaction running? (check I/O)
```

## Scheduled Maintenance

### Monthly Upgrade Window

Recommended schedule:

```crontab
# First Tuesday of month at 2 AM UTC
0 2 ? * TUE /usr/local/bin/smp-scheduled-upgrade.sh
```

**Script template:**
```bash
#!/bin/bash
# /usr/local/bin/smp-scheduled-upgrade.sh

LATEST_VERSION=$(curl -s https://pypi.org/pypi/smp/json | \
  jq -r '.releases | keys | sort_by(-.) | .[0]')

CURRENT_VERSION=$(python3.11 -c "import smp; print(smp.__version__)")

if [ "$CURRENT_VERSION" != "$LATEST_VERSION" ]; then
  echo "Upgrading SMP $CURRENT_VERSION → $LATEST_VERSION"
  # Run upgrade script above
else
  echo "Already on latest version: $CURRENT_VERSION"
fi
```

### Dependency Updates

Check for transitive dependency updates monthly:

```bash
# Check for security updates
pip list --outdated

# Update non-major dependencies
pip install --upgrade pip setuptools wheel

# Run tests after
pytest tests/ -x

# Commit updates
git add pyproject.toml requirements.txt
git commit -m "chore: update dependencies"
```

## Troubleshooting

### Upgrade Hangs

**Symptom:** Server startup hangs after upgrade

**Cause:** Journal replay on large graphs can take minutes

**Solution:**
```bash
# Check process is still running
ps aux | grep smp

# Monitor disk I/O (journal replay)
iotop -o -p $(pgrep -f 'smp.cli')

# Be patient - allow 1 minute per 100k nodes
```

### Compatibility Errors

**Symptom:** "Unknown record type in journal"

**Cause:** Downgrade to older version that doesn't understand new records

**Solution:**
```bash
# Check version mismatch
python3.11 -c "import smp; print(smp.__version__)"

# Re-upgrade to correct version
pip install --force-reinstall 'smp==3.0.0'
```

### Data Corruption After Upgrade

**Symptom:** Integrity check fails after upgrade

**Cause:** Bug in migration or format incompatibility

**Recovery:**
```bash
# Restore from backup
python3.11 -m smp.cli restore \
  --graph-path .smp/graph.smpg \
  --input ./backups/pre-upgrade.tar.gz

# Downgrade
pip install 'smp==2.5.0'

# Contact support with error details
```

## References

- Release Notes: https://github.com/anomalyco/smp/releases
- Python Version Requirements: `ARCHITECTURE.md`
- Database Format: `smp/store/graph/journal.py`
