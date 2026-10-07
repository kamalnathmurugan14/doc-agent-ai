"""Turn an async stream of {"event","data"} dicts into a Server-Sent Events response."""

import json
from collections.abc import AsyncIterator

from sse_starlette.sse import EventSourceResponse


def sse(events: AsyncIterator[dict]) -> EventSourceResponse:
    async def gen():
        try:
            async for ev in events:
                yield {"event": ev["event"], "data": json.dumps(ev["data"], ensure_ascii=False)}
        finally:  # client disconnected or finished: close the upstream (this aborts the Ollama request)
            await events.aclose()  # type: ignore[attr-defined]

    return EventSourceResponse(gen(), ping=15)
