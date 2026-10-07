from fastapi import APIRouter, Request

router = APIRouter(prefix="/agent")


@router.get("/runs")
def list_runs(request: Request, status: str = "", limit: int = 50) -> dict:
    return {"runs": request.app.state.container.runs.list_runs(status, min(max(limit, 1), 200))}


@router.get("/runs/{run_id}")
def get_run(request: Request, run_id: str) -> dict:
    return request.app.state.container.runs.trace(run_id)
