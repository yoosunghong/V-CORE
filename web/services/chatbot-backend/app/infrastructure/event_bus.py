from __future__ import annotations

import asyncio

from app.domain.models import DomainEvent


class InMemoryEventBus:
    def __init__(self) -> None:
        self._events: list[DomainEvent] = []
        self._queues: dict[str, set[asyncio.Queue[DomainEvent]]] = {}

    async def publish(self, event: DomainEvent) -> None:
        self._events.append(event)
        queues = list(self._queues.get(event.session_id, set()))
        for queue in queues:
            await queue.put(event)

    async def history(self, session_id: str) -> list[DomainEvent]:
        return [event for event in self._events if event.session_id == session_id]

    async def subscribe(self, session_id: str) -> asyncio.Queue[DomainEvent]:
        queue: asyncio.Queue[DomainEvent] = asyncio.Queue()
        self._queues.setdefault(session_id, set()).add(queue)
        return queue

    async def unsubscribe(self, session_id: str, queue: asyncio.Queue[DomainEvent]) -> None:
        queues = self._queues.get(session_id)
        if queues is not None:
            queues.discard(queue)
