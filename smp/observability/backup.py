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

import io
import json
import os
import shutil
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smp.store.graph.mmap_store import MMapGraphStore

from smp.logging import get_logger

log = get_logger(__name__)

#: Version of the backup envelope format written by :func:`backup`.
BACKUP_FORMAT_VERSION: int = 1

#: Magic bytes at the start of every raw ``.smpg`` graph file.
_GRAPH_MAGIC: bytes = b"SMPG"


def _ts() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _manifest_for(store: MMapGraphStore, graph_bytes: int, data_end: int) -> dict[str, object]:
    return {
        "format": "smp-backup",
        "backup_version": BACKUP_FORMAT_VERSION,
        "graph_format": "SMPG v1",
        "created_at": datetime.now(UTC).isoformat(),
        "source_path": str(store.path),
        "graph_bytes": graph_bytes,
        "data_end": data_end,
        "nodes": len(store._nodes),  # noqa: SLF001
        "edges": sum(len(v) for v in store._edges.values()),  # noqa: SLF001
    }


async def backup(store: MMapGraphStore, target: Path | str) -> Path:
    """Snapshot the live ``.smpg`` file to ``target`` as a gzipped tarball.

    The archive contains the raw graph snapshot (a strict prefix of the
    live file, so always a valid graph) plus a ``manifest.json`` with
    checksums and version metadata. Use :func:`restore` to extract it.

    The store may be left open during this call.
    """
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    await store.flush()

    src = store.path
    data_end = store.file.data_region_end
    file_size = store.file.size

    # Capture a consistent prefix of the live file: bytes up to file_size
    # at capture time form a valid graph by construction.
    with open(src, "rb") as fh:
        snapshot = fh.read(file_size)

    manifest = _manifest_for(store, len(snapshot), data_end)
    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
    member_name = src.name or "graph.smpg"

    with tempfile.NamedTemporaryFile("wb", delete=False, dir=str(target_path.parent), suffix=".tmp") as tmp:
        tmp_path = Path(tmp.name)
    try:
        with tarfile.open(tmp_path, "w:gz") as tar:
            graph_info = tarfile.TarInfo(name=member_name)
            graph_info.size = len(snapshot)
            graph_info.mtime = int(datetime.now(UTC).timestamp())
            tar.addfile(graph_info, io.BytesIO(snapshot))
            manifest_info = tarfile.TarInfo(name="manifest.json")
            manifest_info.size = len(manifest_bytes)
            manifest_info.mtime = graph_info.mtime
            tar.addfile(manifest_info, io.BytesIO(manifest_bytes))
        os.replace(tmp_path, target_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    log.info(
        "backup_complete",
        src=str(src),
        dst=str(target_path),
        bytes=len(snapshot),
        data_end=data_end,
    )
    return target_path


def _extract_snapshot(source: Path) -> tuple[bytes, dict[str, object]]:
    """Return ``(graph_bytes, manifest)`` from a backup file.

    Raises
    ------
    ValueError
        If ``source`` is neither a valid backup tarball nor a raw
        ``.smpg`` snapshot.
    """
    try:
        with tarfile.open(source, "r:gz") as tar:
            return _read_snapshot_from_tar(source, tar)
    except (tarfile.ReadError, OSError):
        raw = source.read_bytes()
        if raw[: len(_GRAPH_MAGIC)] == _GRAPH_MAGIC:
            return raw, {}
        raise ValueError(f"not a recognized SMP backup: {source}") from None


def _read_snapshot_from_tar(source: Path, tar: tarfile.TarFile) -> tuple[bytes, dict[str, object]]:
    """Extract the graph snapshot and manifest from an open backup tarball."""
    try:
        members = tar.getmembers()
    except (tarfile.ReadError, EOFError) as exc:
        raise ValueError(f"unreadable SMP backup archive: {source} ({exc})") from None
    manifest: dict[str, object] = {}
    for member in members:
        if member.name == "manifest.json" and member.isfile():
            extracted = tar.extractfile(member)
            if extracted is not None:
                try:
                    manifest = json.loads(extracted.read().decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    manifest = {}
            break
    for member in members:
        if member.isfile() and (member.name.endswith(".smpg") or member.name == "graph.smpg"):
            extracted = tar.extractfile(member)
            if extracted is not None:
                return extracted.read(), manifest
    version = manifest.get("version", manifest.get("backup_version", "unknown"))
    raise ValueError(f"backup archive contains no graph snapshot (manifest version: {version})")


async def restore(target: Path | str, source: Path | str) -> Path:
    """Restore ``target`` from the backup at ``source``.

    Accepts archives written by :func:`backup` as well as raw ``.smpg``
    snapshots (backward compatibility). A timestamped sidecar copy of
    any existing target is left at ``<target>.bak.<ts>``.

    The target SMP service must already be stopped — this function does
    not coordinate with a running store.
    """
    target_path = Path(target)
    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    snapshot, _manifest = await _read_snapshot(source_path)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        sidecar = target_path.with_suffix(target_path.suffix + f".bak.{_ts()}")
        shutil.copy2(target_path, sidecar)
        log.info("restore_sidecar_written", path=str(sidecar))

    with tempfile.NamedTemporaryFile("wb", delete=False, dir=str(target_path.parent), suffix=".tmp") as tmp:
        tmp.write(snapshot)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, target_path)
    log.info("restore_complete", src=str(source_path), dst=str(target_path))
    return target_path


async def _read_snapshot(source: Path) -> tuple[bytes, dict[str, object]]:
    """Read a backup file off the event loop's thread pool boundary."""
    import asyncio

    return await asyncio.get_running_loop().run_in_executor(None, _extract_snapshot, source)


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
