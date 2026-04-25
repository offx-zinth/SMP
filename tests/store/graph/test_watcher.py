"""Tests for ``smp.store.graph.watcher`` and watcher integration with ``MMapGraphStore``."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from pathlib import Path

from smp.store.graph.mmap_store import MMapGraphStore
from smp.store.graph.watcher import (
    DEFAULT_DEBOUNCE_SECONDS,
    FileWatcher,
)

EVENT_WAIT_SECONDS: float = 5.0
SETTLE_SECONDS: float = 0.5


def _wait_for(predicate: Callable[[], bool], timeout: float = EVENT_WAIT_SECONDS) -> bool:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if predicate():
            return True
        time.sleep(0.05)
    return False


class _Recorder:
    """Thread-safe collector of (path, event_type) pairs."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def __call__(self, path: str, event_type: str) -> None:
        with self._lock:
            self.events.append((path, event_type))

    def find(self, suffix: str, event_type: str) -> bool:
        with self._lock:
            return any(p.endswith(suffix) and t == event_type for p, t in self.events)

    def count(self, suffix: str, event_type: str) -> int:
        with self._lock:
            return sum(1 for p, t in self.events if p.endswith(suffix) and t == event_type)

    def clear(self) -> None:
        with self._lock:
            self.events.clear()


# ---------------------------------------------------------------------------
# FileWatcher unit tests
# ---------------------------------------------------------------------------


class TestFileWatcher:
    def test_lifecycle(self, tmp_path: Path) -> None:
        recorder = _Recorder()
        watcher = FileWatcher(recorder)
        watcher.watch_directory(tmp_path)
        watcher.start()
        assert watcher.is_running
        assert watcher.backend in ("native", "polling")
        watcher.stop()
        assert not watcher.is_running

    def test_detects_create(self, tmp_path: Path) -> None:
        recorder = _Recorder()
        watcher = FileWatcher(recorder, debounce_seconds=0.01)
        watcher.watch_directory(tmp_path)
        watcher.start()
        try:
            time.sleep(SETTLE_SECONDS)
            target = tmp_path / "created.py"
            target.write_text("x = 1\n")
            assert _wait_for(lambda: recorder.find("created.py", "created") or recorder.find("created.py", "modified"))
        finally:
            watcher.stop()

    def test_detects_modify(self, tmp_path: Path) -> None:
        target = tmp_path / "mod.py"
        target.write_text("x = 1\n")

        recorder = _Recorder()
        watcher = FileWatcher(recorder, debounce_seconds=0.01)
        watcher.watch_directory(tmp_path)
        watcher.start()
        try:
            time.sleep(SETTLE_SECONDS)
            target.write_text("x = 2\n")
            assert _wait_for(lambda: recorder.find("mod.py", "modified"))
        finally:
            watcher.stop()

    def test_detects_delete(self, tmp_path: Path) -> None:
        target = tmp_path / "gone.py"
        target.write_text("x = 1\n")

        recorder = _Recorder()
        watcher = FileWatcher(recorder, debounce_seconds=0.01)
        watcher.watch_directory(tmp_path)
        watcher.start()
        try:
            time.sleep(SETTLE_SECONDS)
            target.unlink()
            assert _wait_for(lambda: recorder.find("gone.py", "deleted"))
        finally:
            watcher.stop()

    def test_extension_filter(self, tmp_path: Path) -> None:
        recorder = _Recorder()
        watcher = FileWatcher(recorder, extensions={".py"}, debounce_seconds=0.01)
        watcher.watch_directory(tmp_path)
        watcher.start()
        try:
            time.sleep(SETTLE_SECONDS)
            (tmp_path / "ignored.txt").write_text("hi\n")
            (tmp_path / "kept.py").write_text("y = 1\n")
            assert _wait_for(lambda: recorder.find("kept.py", "created") or recorder.find("kept.py", "modified"))
            time.sleep(SETTLE_SECONDS)
            assert not recorder.find("ignored.txt", "created")
            assert not recorder.find("ignored.txt", "modified")
        finally:
            watcher.stop()

    def test_debounce_collapses_bursts(self, tmp_path: Path) -> None:
        target = tmp_path / "burst.py"
        target.write_text("v = 0\n")

        recorder = _Recorder()
        watcher = FileWatcher(recorder, debounce_seconds=2.0)
        watcher.watch_directory(tmp_path)
        watcher.start()
        try:
            time.sleep(SETTLE_SECONDS)
            for i in range(10):
                target.write_text(f"v = {i}\n")
                time.sleep(0.05)
            time.sleep(0.5)
            count = recorder.count("burst.py", "modified")
            assert count <= 1, f"expected debounce to collapse bursts, saw {count} events"
        finally:
            watcher.stop()

    def test_unwatch_directory(self, tmp_path: Path) -> None:
        recorder = _Recorder()
        watcher = FileWatcher(recorder, debounce_seconds=0.01)
        watcher.watch_directory(tmp_path)
        watcher.start()
        try:
            time.sleep(SETTLE_SECONDS)
            (tmp_path / "first.py").write_text("a = 1\n")
            assert _wait_for(lambda: recorder.find("first.py", "created") or recorder.find("first.py", "modified"))

            watcher.unwatch_directory(tmp_path)
            time.sleep(SETTLE_SECONDS)
            recorder.clear()

            (tmp_path / "second.py").write_text("b = 1\n")
            time.sleep(SETTLE_SECONDS + 0.5)
            assert recorder.count("second.py", "created") == 0
            assert recorder.count("second.py", "modified") == 0
        finally:
            watcher.stop()

    def test_default_debounce_constant(self) -> None:
        assert DEFAULT_DEBOUNCE_SECONDS > 0


# ---------------------------------------------------------------------------
# MMapGraphStore stale detection / re-parse integration
# ---------------------------------------------------------------------------


async def _await_hash_change(
    store: MMapGraphStore,
    resolved_path: str,
    initial_hash: str,
    timeout: float = EVENT_WAIT_SECONDS,
) -> bool:
    """Block until the file's stored hash differs from ``initial_hash``."""
    start = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start < timeout:
        current = store._file_hashes.get(resolved_path)
        if current is not None and current != initial_hash:
            return True
        await asyncio.sleep(0.05)
    return False


async def _await_predicate(
    predicate: Callable[[], object],
    timeout: float = EVENT_WAIT_SECONDS,
) -> bool:
    start = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start < timeout:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


class TestStaleDetection:
    async def test_modify_triggers_reparse(self, tmp_path: Path) -> None:
        src = tmp_path / "calc.py"
        src.write_bytes(b"def add(a, b):\n    return a + b\n")
        db = tmp_path / "graph.smpg"

        store = MMapGraphStore(db)
        await store.connect()
        try:
            await store.parse_file(str(src))
            resolved = str(src.resolve())
            initial_hash = store._file_hashes[resolved]
            assert initial_hash

            store.watch_directories([tmp_path])
            await asyncio.sleep(SETTLE_SECONDS)

            src.write_bytes(b"def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n")

            assert await _await_hash_change(store, resolved, initial_hash, timeout=10.0)

            status = await store.get_parse_status(resolved)
            assert status.parsed
            assert not status.stale

            nodes = await store.find_nodes(file_path=resolved)
            names = {n.structural.name for n in nodes}
            assert "sub" in names
            assert "add" in names
        finally:
            await store.close()

    async def test_delete_removes_nodes(self, tmp_path: Path) -> None:
        src = tmp_path / "doomed.py"
        src.write_bytes(b"def foo():\n    pass\n")
        db = tmp_path / "graph.smpg"

        store = MMapGraphStore(db)
        await store.connect()
        try:
            await store.parse_file(str(src))
            resolved = str(src.resolve())
            assert await store.find_nodes(file_path=resolved)

            store.watch_directories([tmp_path])
            await asyncio.sleep(SETTLE_SECONDS)

            src.unlink()

            async def gone() -> bool:
                return not (await store.find_nodes(file_path=resolved))

            start = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start < EVENT_WAIT_SECONDS:
                if await gone():
                    break
                await asyncio.sleep(0.05)

            assert await gone()
            assert resolved not in store._file_hashes
            status = await store.get_parse_status(resolved)
            assert not status.parsed
        finally:
            await store.close()

    async def test_invalidate_file_marks_stale_and_reparses(self, tmp_path: Path) -> None:
        src = tmp_path / "inv.py"
        src.write_bytes(b"def one():\n    return 1\n")
        db = tmp_path / "graph.smpg"

        store = MMapGraphStore(db)
        await store.connect()
        try:
            await store.parse_file(str(src))
            resolved = str(src.resolve())
            initial_hash = store._file_hashes[resolved]

            src.write_bytes(b"def one():\n    return 1\n\ndef two():\n    return 2\n")

            await store.invalidate_file(str(src))

            assert await _await_hash_change(store, resolved, initial_hash, timeout=10.0)

            nodes = await store.find_nodes(file_path=resolved)
            names = {n.structural.name for n in nodes}
            assert {"one", "two"} <= names
        finally:
            await store.close()

    async def test_invalidate_missing_file_cleans_up(self, tmp_path: Path) -> None:
        src = tmp_path / "ghost.py"
        src.write_bytes(b"def ghost():\n    pass\n")
        db = tmp_path / "graph.smpg"

        store = MMapGraphStore(db)
        await store.connect()
        try:
            await store.parse_file(str(src))
            resolved = str(src.resolve())
            assert await store.find_nodes(file_path=resolved)

            src.unlink()

            await store.invalidate_file(str(src))

            assert not (await store.find_nodes(file_path=resolved))
            assert resolved not in store._file_hashes
        finally:
            await store.close()


# ---------------------------------------------------------------------------
# Re-parse correctness: ensure deleted symbols disappear
# ---------------------------------------------------------------------------


class TestReparseSemantics:
    async def test_reparse_purges_removed_symbols(self, tmp_path: Path) -> None:
        src = tmp_path / "evolve.py"
        src.write_bytes(b"def keep():\n    pass\n\ndef remove_me():\n    pass\n")
        db = tmp_path / "graph.smpg"

        store = MMapGraphStore(db)
        await store.connect()
        try:
            await store.parse_file(str(src))
            resolved = str(src.resolve())
            names = {n.structural.name for n in await store.find_nodes(file_path=resolved)}
            assert {"keep", "remove_me"} <= names

            src.write_bytes(b"def keep():\n    pass\n")
            await store.parse_file(str(src))

            names = {n.structural.name for n in await store.find_nodes(file_path=resolved)}
            assert "keep" in names
            assert "remove_me" not in names
        finally:
            await store.close()
