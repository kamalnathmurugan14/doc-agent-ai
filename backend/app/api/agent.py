from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.sse import sse
from app.errors import AppError

router = APIRouter(prefix="/agent")


class Scope(BaseModel):
    files: list[str] = []
    folders: list[str] = []


class RunIn(BaseModel):
    task: str = Field(min_length=1, max_length=4000)
    runtime: str = "react"
    scope: Scope | None = None
    max_steps: int | None = Field(default=None, ge=1, le=50)
    dry_run: bool = False
    plan: bool = False


@router.post("/run")
async def run(request: Request, body: RunIn):
    """Starts a run and streams its events (SSE). The run continues even if the browser disconnects."""
    live = await request.app.state.container.runs.start(
        body.task,
        body.runtime,
        body.scope.model_dump() if body.scope else None,
        body.max_steps,
        body.dry_run,
        body.plan,
    )
    return sse(live.bus.subscribe())


@router.get("/runs/{run_id}/events")
async def events(request: Request, run_id: str):
    """Re-attach to the live event stream of a running run (history is replayed first)."""
    live = request.app.state.container.runs.live.get(run_id)
    if live is None:
        raise AppError(
            "NOT_LIVE", "This run is not active in this server process; use GET /agent/runs/{id} for its trace", 404
        )
    return sse(live.bus.subscribe())


@router.post("/runs/{run_id}/cancel")
def cancel(request: Request, run_id: str) -> dict:
    runs = request.app.state.container.runs
    runs.get_row(run_id)
    return {"cancelled": runs.cancel(run_id)}
