from __future__ import annotations

import heapq
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass(order=True)
class ParseTask:
    """A file waiting to be parsed."""

    priority: float
    file_path: str = field(compare=False)
    enqueued_at: float = field(compare=False, default_factory=time.time)
    in_degree: int = field(compare=False, default=0)


class BackgroundScheduler:
    """Background pre-parse scheduler with priority queue."""

    def __init__(
        self,
        parser: Any,
        max_workers: int | None = None,
    ) -> None:
        self.parser = parser
        self._max_workers = max_workers or min(32, (os.cpu_count() or 1) + 4)
        self._queue: list[ParseTask] = []
        self._enqueued: set[str] = set()
        self._lock = threading.Lock()
        self._workers: list[threading.Thread] = []
        self._stopping = threading.Event()
        self._parse_callback: Callable[[str, Any], None] | None = None

    @property
    def callback(self) -> Callable[[str, Any], None] | None:
        return self._parse_callback

    @callback.setter
    def callback(self, cb: Callable[[str, Any], None]) -> None:
        self._parse_callback = cb

    def start(self) -> None:
        """Start worker threads."""
        if self._workers:
            return
        self._stopping.clear()
        for i in range(self._max_workers):
            t = threading.Thread(target=self._worker, daemon=True, name=f"smp-parse-{i}")
            t.start()
            self._workers.append(t)
        log.info("scheduler_started", extra={"worker_count": self._max_workers})

    def stop(self, timeout: float = 5.0) -> None:
        """Stop worker threads gracefully."""
        self._stopping.set()
        for t in self._workers:
            t.join(timeout=timeout)
        self._workers.clear()
        log.info("scheduler_stopped")

    def enqueue(self, file_path: str, priority: float = 50.0, in_degree: int = 0) -> bool:
        """Add a file to the parse queue. Returns True if newly enqueued."""
        with self._lock:
            if file_path in self._enqueued:
                return False
            self._enqueued.add(file_path)
            task = ParseTask(priority=priority, file_path=file_path, in_degree=in_degree)
            heapq.heappush(self._queue, task)
            log.debug("task_enqueued", extra={"file_path": file_path, "priority": priority})
            return True

    def enqueue_batch(self, files: list[tuple[str, float, int]]) -> int:
        """Batch enqueue files. Returns count newly enqueued."""
        count = 0
        with self._lock:
            for file_path, priority, in_degree in files:
                if file_path not in self._enqueued:
                    self._enqueued.add(file_path)
                    heapq.heappush(
                        self._queue,
                        ParseTask(
                            priority=priority,
                            file_path=file_path,
                            in_degree=in_degree,
                        ),
                    )
                    count += 1
        return count

    def dequeue(self) -> ParseTask | None:
        """Get next task from queue."""
        with self._lock:
            if not self._queue:
                return None
            return heapq.heappop(self._queue)

    @property
    def pending_count(self) -> int:
        """Number of tasks waiting to be processed."""
        with self._lock:
            return len(self._queue)

    def _worker(self) -> None:
        """Worker thread that processes parse tasks."""
        while not self._stopping.is_set():
            task = self.dequeue()
            if task is None:
                time.sleep(0.1)
                continue

            try:
                parsed = self.parser.parse_file(task.file_path)
                if self._parse_callback:
                    self._parse_callback(task.file_path, parsed)
                log.debug("task_completed", extra={"file_path": task.file_path})
            except Exception:
                log.exception("task_failed", extra={"file_path": task.file_path})
            finally:
                with self._lock:
                    self._enqueued.discard(task.file_path)
