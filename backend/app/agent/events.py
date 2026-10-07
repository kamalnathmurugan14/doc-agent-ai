"""In-memory event bus for one run: replays history to late subscribers (SSE reconnects) and streams new events live."""

import asyncio
from collections.abc import AsyncIterator

EVENT_TYPES = (
    "run_started",
    "plan",
    "thought",
    "action",
    "observation",
    "approval_required",
    "approval_resolved",
    "final",
    "error",
    "max_steps_reached",
)


class RunBus:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.closed = False
        self._cond = asyncio.Condition()

    async def emit(self, event: str, data: dict) -> None:
        async with self._cond:
            self.events.append({"event": event, "data": data})
            self._cond.notify_all()

    async def close(self) -> None:
        async with self._cond:
            self.closed = True
            self._cond.notify_all()

    async def subscribe(self) -> AsyncIterator[dict]:
        i = 0
        while True:
            async with self._cond:
                await self._cond.wait_for(lambda idx=i: idx < len(self.events) or self.closed)
                if i >= len(self.events):
                    return
                ev = self.events[i]
            i += 1
            yield ev
