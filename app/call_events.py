"""In-process pub/sub for call lifecycle and transcript events.

The voice pipeline publishes; each open console page subscribes with its own queue.
Everything lives in one process, so the server must run with a single worker.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

EventKind = Literal['dialing', 'call_started', 'transcript', 'call_ended']
Direction = Literal['inbound', 'outbound']
Role = Literal['user', 'agent']


@dataclass(frozen=True)
class CallEvent:
    kind: EventKind
    call_sid: str
    timestamp: datetime  # timezone-aware
    direction: Direction | None = None
    remote_number: str = ''
    role: Role | None = None  # transcript events only
    text: str = ''
    duration_sec: float | None = None  # call_ended events only


class CallEventHub:
    def __init__(self, history_size: int = 500, queue_size: int = 1000) -> None:
        self._history: deque[CallEvent] = deque(maxlen=history_size)
        self._queue_size = queue_size
        self._subscribers: set[asyncio.Queue[CallEvent]] = set()

    def publish(self, event: CallEvent) -> None:
        """Record and fan out an event. Never blocks, so a slow page cannot stall a call."""
        self._history.append(event)
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # the page stopped draining; it can recover from history on reload

    def subscribe(self) -> asyncio.Queue[CallEvent]:
        queue: asyncio.Queue[CallEvent] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[CallEvent]) -> None:
        self._subscribers.discard(queue)

    def history(self) -> list[CallEvent]:
        return list(self._history)


def utc_now() -> datetime:
    return datetime.now(UTC)


class CallReporter:
    """Publishes one call's lifecycle and transcript events, stamped with the call's details."""

    def __init__(
        self,
        hub: CallEventHub,
        *,
        call_sid: str,
        direction: Direction,
        remote_number: str,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._hub = hub
        self._call_sid = call_sid
        self._direction = direction
        self._remote_number = remote_number
        self._clock = clock

    def _publish(self, kind: EventKind, timestamp: datetime | None = None, **fields) -> None:
        self._hub.publish(
            CallEvent(
                kind=kind,
                call_sid=self._call_sid,
                timestamp=timestamp or self._clock(),
                direction=self._direction,
                remote_number=self._remote_number,
                **fields,
            )
        )

    def started(self) -> None:
        self._publish('call_started')

    async def transcript(self, role: Role, text: str, timestamp_iso: str) -> None:
        """Matches app.realtime.TranscriptCallback."""
        self._publish('transcript', self._parse_timestamp(timestamp_iso), role=role, text=text)

    def ended(self, duration_sec: float) -> None:
        self._publish('call_ended', duration_sec=duration_sec)

    def _parse_timestamp(self, value: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


hub = CallEventHub()
