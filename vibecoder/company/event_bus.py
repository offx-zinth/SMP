from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

EventHandler = Callable[["Event"], Awaitable[None]]


@dataclass(slots=True, frozen=True)
class Event:
    """Message exchanged between personas through the enterprise event bus."""

    topic: str
    payload: dict[str, Any] = field(default_factory=dict)
    sender: str = "system"


class AsyncEventBus:
    """Async pub/sub bus with bounded queue and fan-out worker dispatch."""

    def __init__(self, *, queue_size: int = 1000, worker_count: int = 4) -> None:
        if queue_size <= 0:
            raise ValueError("queue_size must be positive")
        if worker_count <= 0:
            raise ValueError("worker_count must be positive")

        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=queue_size)
        self._subscriptions: defaultdict[str, list[EventHandler]] = defaultdict(list)
        self._workers: list[asyncio.Task[None]] = []
        self._shutdown = asyncio.Event()
        self._started = False
        self._worker_count = worker_count

    async def start(self) -> None:
        """Start background workers if not already running."""
        if self._started:
            return
        self._shutdown.clear()
        self._workers = [
            asyncio.create_task(self._worker_loop(index), name=f"event-bus-worker-{index}")
            for index in range(self._worker_count)
        ]
        self._started = True

    async def stop(self) -> None:
        """Gracefully stop workers after draining queued events."""
        if not self._started:
            return

        await self._queue.join()
        self._shutdown.set()

        for worker in self._workers:
            worker.cancel()

        for worker in self._workers:
            with contextlib.suppress(asyncio.CancelledError):
                await worker

        self._workers.clear()
        self._started = False

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        """Register an async callback for a topic."""
        if not topic:
            raise ValueError("topic cannot be empty")
        self._subscriptions[topic].append(handler)

    async def publish(self, event: Event) -> None:
        """Publish an event to the queue for async processing."""
        if not self._started:
            raise RuntimeError("Event bus must be started before publishing")
        await self._queue.put(event)

    async def _worker_loop(self, worker_index: int) -> None:
        while not self._shutdown.is_set():
            event = await self._queue.get()
            try:
                await self._dispatch(event)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Worker %s failed dispatching topic=%s: %s", worker_index, event.topic, exc)
            finally:
                self._queue.task_done()

    async def _dispatch(self, event: Event) -> None:
        handlers = list(self._subscriptions.get(event.topic, []))
        if not handlers:
            logger.debug("No subscribers for topic=%s", event.topic)
            return

        results = await asyncio.gather(*(handler(event) for handler in handlers), return_exceptions=True)
        for handler, result in zip(handlers, results, strict=False):
            if isinstance(result, Exception):
                logger.exception(
                    "Subscriber %s raised while handling topic=%s",
                    getattr(handler, "__qualname__", str(handler)),
                    event.topic,
                    exc_info=result,
                )
