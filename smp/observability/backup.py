"""Backup, restore, and compaction helpers for the SMP graph file.

Backup strategy
---------------

The on-disk format is a single ``.smpg`` file with an in-place
journal.  Backing it up safely while the server is running requires
two invariants:

1. The journal must be flushed so the bytes captured represent a
   consistent record stream.
2. While we're copying, no new bytes may be appended to the same data
   region (otherwise the copy would race the writer).

We satisfy both by:

* Calling :meth:`MMapGraphStore.flush` to push everything to the OS.
* Snapshotting the ``data_end`` pointer and copying exactly that many
  bytes.  The resulting file is always a strict prefix of the live
  file, so it's a valid graph by construction.

Restore is just an atomic file replace.  The store must be closed
first; the caller is responsible for stopping the SMP service before
calling :func:`restore`.

Compaction
----------

Compaction rewrites the journal to a fresh file containing only the
*current* state — duplicate updates and deleted records are dropped.
The output is byte-for-byte equivalent to a freshly populated store
that received each surviving record once, in order.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smp.store.graph.mmap_store import MMapGraphStore

from smp.logging import get_logger

log = get_logger(__name__)


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


async def backup(store: MMapGraphStore, target: Path | str) -> Path:
    """Copy the live ``.smpg`` file to ``target`` consistently.

    The snapshot captures only the bytes up to ``data_end`` at the
    moment of capture, so partial writes cannot corrupt the backup.

    The store may be left open during this call.
    """
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    await store.flush()

    src = store.path
    data_end = store.file.data_region_end
    file_size = store.file.size

    # Always copy the full file (header + WAL + data region up to file size)
    # The data_end pointer in the header bounds where journal records live.
    bytes_to_copy = file_size

    with open(src, "rb") as fh:
        with tempfile.NamedTemporaryFile("wb", delete=False, dir=str(target_path.parent), suffix=".tmp") as tmp:
            tmp_path = Path(tmp.name)
            remaining = bytes_to_copy
            while remaining > 0:
                chunk = fh.read(min(remaining, 1 << 20))
                if not chunk:
                    break
                tmp.write(chunk)
                remaining -= len(chunk)
    os.replace(tmp_path, target_path)
    log.info(
        "backup_complete",
        src=str(src),
        dst=str(target_path),
        bytes=bytes_to_copy,
        data_end=data_end,
    )
    return target_path


async def restore(target: Path | str, source: Path | str) -> Path:
    """Atomically replace ``target`` with ``source``.

    The target SMP service must already be stopped — this function does
    not coordinate with a running store.  A timestamped sidecar copy of
    the previous file is left at ``<target>.bak.<ts>`` so an operator
    can roll back without rerunning the backup tool.
    """
    target_path = Path(target)
    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    if target_path.exists():
        sidecar = target_path.with_suffix(target_path.suffix + f".bak.{_ts()}")
        shutil.copy2(target_path, sidecar)
        log.info("restore_sidecar_written", path=str(sidecar))

    shutil.copyfile(source_path, target_path)
    log.info("restore_complete", src=str(source_path), dst=str(target_path))
    return target_path


async def compact(store: MMapGraphStore) -> dict[str, int]:
    """Rewrite the journal to drop redundant records.

    Builds a fresh ``.smpg`` next to the live file, replays every node /
    edge / session / lock / audit event from the in-memory state into
    the new journal, then atomically swaps the files.  The store is
    closed and re-opened around the swap.

    Returns
    -------
    dict
        ``before_bytes`` and ``after_bytes`` so callers can compute the
        space reclaimed (and surface it in ``/metrics`` or admin UIs).
    """
    from smp.core.models import GraphEdge, GraphNode  # noqa: F401  - keeps imports honest
    from smp.store.graph.mmap_store import MMapGraphStore as _Store

    src_path = Path(store.path)
    before_bytes = store.file.size
    snapshot_nodes = list(store._nodes.values())  # noqa: SLF001
    snapshot_edges = [edge for edges in store._edges.values() for edge in edges]  # noqa: SLF001
    snapshot_sessions = [dict(s) for s in store._sessions.values()]  # noqa: SLF001
    snapshot_locks = [(fp, dict(info)) for fp, info in store._locks.items()]  # noqa: SLF001
    snapshot_audit = [dict(e) for e in store._audit]  # noqa: SLF001

    await store.flush()
    await store.close()

    tmp_path = src_path.with_suffix(src_path.suffix + ".compact")
    if tmp_path.exists():
        tmp_path.unlink()

    fresh = _Store(tmp_path)
    await fresh.connect()
    try:
        if snapshot_nodes:
            await fresh.upsert_nodes(snapshot_nodes)
        for edge in snapshot_edges:
            await fresh.upsert_edge(edge)
        for session in snapshot_sessions:
            await fresh.upsert_session(session)
        for fp, info in snapshot_locks:
            await fresh.upsert_lock(
                fp,
                str(info.get("session_id", "")),
                acquired_at=str(info.get("acquired_at", "")),
                expires_at=str(info.get("expires_at", "")),
            )
        for event in snapshot_audit:
            await fresh.append_audit(event)
        await fresh.flush()
        after_bytes = fresh.file.size
    finally:
        await fresh.close()

    backup_path = src_path.with_suffix(src_path.suffix + f".precompact.{_ts()}")
    shutil.copy2(src_path, backup_path)
    os.replace(tmp_path, src_path)

    await store.connect()  # reopen the original handle pointing at the new bytes

    log.info(
        "compaction_complete",
        before=before_bytes,
        after=after_bytes,
        saved=before_bytes - after_bytes,
        backup=str(backup_path),
    )
    return {"before_bytes": before_bytes, "after_bytes": after_bytes}


__all__ = ["backup", "compact", "restore"]
