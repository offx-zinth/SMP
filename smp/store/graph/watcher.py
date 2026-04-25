"""File system watcher for live graph updates.

Implements a hybrid watching strategy as described in ``SPEC.md``:

* **Tier 1 (native):** Uses :class:`watchdog.observers.Observer` which dispatches
  to the platform-native API (``inotify`` on Linux, ``ReadDirectoryChangesW`` on
  Windows, ``FSEvents`` on macOS).
* **Tier 2 (polling):** Falls back to :class:`watchdog.observers.polling.PollingObserver`
  when the native observer fails to start (e.g. ``inotify`` watch limit reached).

The watcher debounces rapid event bursts on the same path (editors typically
emit several events per save: write, flush, atomic rename, etc.) and filters
events by file extension so only source files of interest reach the callback.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from watchdog.events import (
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver
from watchdog.observers.polling import PollingObserver

from smp.logging import get_logger

log = get_logger(__name__)

DEFAULT_DEBOUNCE_SECONDS: float = 0.5
DEFAULT_POLL_INTERVAL_SECONDS: float = 60.0
DEFAULT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".java",
        ".c",
        ".cc",
        ".cpp",
        ".cxx",
        ".h",
        ".hpp",
        ".cs",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".swift",
        ".kt",
        ".kts",
        ".m",
    }
)

WatcherCallback = Callable[[str, str], None]


class _EventHandler(FileSystemEventHandler):
    """Translates watchdog events into normalised callbacks with debouncing."""

    def __init__(
        self,
        callback: WatcherCallback,
        extensions: frozenset[str],
        debounce_seconds: float,
    ) -> None:
        super().__init__()
        self._callback = callback
        self._extensions = extensions
        self._debounce_seconds = debounce_seconds
        self._last_event: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def _accepts(self, src_path: str) -> bool:
        suffix = Path(src_path).suffix.lower()
        if not self._extensions:
            return True
        return suffix in self._extensions

    def _normalise(self, src_path: str) -> str:
        try:
            return str(Path(src_path).resolve())
        except OSError:
            return str(Path(src_path).absolute())

    def _dispatch(self, path: str, event_type: str) -> None:
        key = (path, event_type)
        now = time.monotonic()
        with self._lock:
            last = self._last_event.get(key, 0.0)
            if now - last < self._debounce_seconds:
                return
            self._last_event[key] = now
        try:
            self._callback(path, event_type)
        except Exception:
            log.exception("watcher_callback_failed", path=path, event_type=event_type)

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        src = str(event.src_path)
        if not self._accepts(src):
            return
        self._dispatch(self._normalise(src), "created")

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        src = str(event.src_path)
        if not self._accepts(src):
            return
        self._dispatch(self._normalise(src), "modified")

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        src = str(event.src_path)
        if not self._accepts(src):
            return
        self._dispatch(self._normalise(src), "deleted")

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        src = str(event.src_path)
        dest_attr: Any = getattr(event, "dest_path", "")
        dest = str(dest_attr) if dest_attr else ""
        if self._accepts(src):
            self._dispatch(self._normalise(src), "deleted")
        if dest and self._accepts(dest):
            self._dispatch(self._normalise(dest), "created")


class FileWatcher:
    """Cross-platform file system watcher with polling fallback.

    Args:
        callback: Invoked as ``callback(absolute_path, event_type)`` where
            ``event_type`` is one of ``"created"``, ``"modified"``,
            ``"deleted"``.  Move events are translated into ``deleted`` for the
            source path and ``created`` for the destination.
        extensions: File suffixes (with leading ``.``) to include.  Pass an
            empty set to receive events for all files.  Defaults to a
            curated set of source-code extensions.
        debounce_seconds: Window during which duplicate ``(path, event_type)``
            events are coalesced.  Default ``0.5`` seconds.
        poll_interval: Polling cadence used when the native observer fails to
            start.  Default ``60`` seconds (matches the spec).
    """

    def __init__(
        self,
        callback: WatcherCallback,
        *,
        extensions: Iterable[str] | None = None,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ) -> None:
        ext_set = DEFAULT_EXTENSIONS if extensions is None else frozenset(e.lower() for e in extensions)
        self._handler = _EventHandler(callback, ext_set, debounce_seconds)
        self._poll_interval = poll_interval
        self._observer: BaseObserver | None = None
        self._backend: str = "native"
        self._watches: dict[str, Any] = {}
        self._started = False
        self._lock = threading.Lock()

    @property
    def backend(self) -> str:
        """Return the currently active backend: ``"native"`` or ``"polling"``."""
        return self._backend

    @property
    def is_running(self) -> bool:
        return self._started and self._observer is not None and self._observer.is_alive()

    def _build_observer(self, *, polling: bool) -> BaseObserver:
        if polling:
            return PollingObserver(timeout=self._poll_interval)
        return Observer()

    def watch_directory(self, path: str | Path, *, recursive: bool = True) -> None:
        """Add ``path`` to the watch set.

        May be called before or after :meth:`start`.  When called before, the
        path is registered with the observer when ``start`` is invoked.
        """
        resolved = str(Path(path).resolve())
        with self._lock:
            if resolved in self._watches:
                return
            if self._observer is not None:
                watch = self._observer.schedule(self._handler, resolved, recursive=recursive)
                self._watches[resolved] = watch
            else:
                self._watches[resolved] = ("pending", recursive)
        log.info("watch_directory_added", path=resolved, backend=self._backend)

    def unwatch_directory(self, path: str | Path) -> None:
        """Remove ``path`` from the watch set."""
        resolved = str(Path(path).resolve())
        with self._lock:
            entry = self._watches.pop(resolved, None)
            if entry is None:
                return
            if self._observer is not None and not isinstance(entry, tuple):
                with contextlib.suppress(KeyError, ValueError):
                    self._observer.unschedule(entry)
        log.info("watch_directory_removed", path=resolved)

    def start(self) -> None:
        """Start the observer thread.  Falls back to polling on failure."""
        with self._lock:
            if self._started:
                return
            pending: list[tuple[str, bool]] = []
            for resolved, entry in list(self._watches.items()):
                if isinstance(entry, tuple) and entry[0] == "pending":
                    pending.append((resolved, bool(entry[1])))

            try:
                observer = self._build_observer(polling=False)
                for resolved, recursive in pending:
                    self._watches[resolved] = observer.schedule(self._handler, resolved, recursive=recursive)
                observer.start()
                self._observer = observer
                self._backend = "native"
            except (OSError, RuntimeError) as exc:
                log.warning("watcher_native_failed", error=str(exc))
                observer = self._build_observer(polling=True)
                for resolved, recursive in pending:
                    self._watches[resolved] = observer.schedule(self._handler, resolved, recursive=recursive)
                observer.start()
                self._observer = observer
                self._backend = "polling"

            self._started = True
        log.info("watcher_started", backend=self._backend, watch_count=len(self._watches))

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the observer thread."""
        with self._lock:
            observer = self._observer
            self._observer = None
            self._started = False
        if observer is None:
            return
        try:
            observer.stop()
            observer.join(timeout=timeout)
        except RuntimeError:
            pass
        log.info("watcher_stopped")
