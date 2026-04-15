"""Notification manager for server-push events.

Provides a polling-based notification system for clients to receive
real-time updates about graph changes, session events, etc.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from smp.logging import get_logger

log = get_logger(__name__)


@dataclass
class Notification:
    """A single notification event."""

    notification_id: str
    event_type: str
    payload: dict[str, Any]
    timestamp: str
    session_id: str = ""


class NotificationManager:
    """Manages notifications with in-memory storage."""

    def __init__(self, max_events: int = 1000) -> None:
        self._events: list[Notification] = []
        self._max_events = max_events
        self._subscribers: dict[str, asyncio.Queue[Notification]] = {}

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        session_id: str = "",
    ) -> None:
        """Emit a new notification event."""
        notification = Notification(
            notification_id=f"notif_{len(self._events)}",
            event_type=event_type,
            payload=payload,
            timestamp=datetime.now(UTC).isoformat(),
            session_id=session_id,
        )
        self._events.append(notification)

        # Trim if exceeding max
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events :]

        log.debug("notification_emitted", event_type=event_type)

    def poll(self, last_seen: int = 0) -> list[dict[str, Any]]:
        """Poll for new notifications since last_seen index."""
        if last_seen >= len(self._events):
            return []

        recent = self._events[last_seen:]
        return [
            {
                "index": last_seen + i,
                "notification_id": n.notification_id,
                "event_type": n.event_type,
                "payload": n.payload,
                "timestamp": n.timestamp,
                "session_id": n.session_id,
            }
            for i, n in enumerate(recent)
        ]

    def get_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get the most recent notifications."""
        recent = self._events[-limit:]
        return [
            {
                "notification_id": n.notification_id,
                "event_type": n.event_type,
                "payload": n.payload,
                "timestamp": n.timestamp,
                "session_id": n.session_id,
            }
            for n in recent
        ]
