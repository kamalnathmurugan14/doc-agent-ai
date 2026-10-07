from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.errors import AppError
from app.services.approval_service import Decision

router = APIRouter(prefix="/agent")


class ApproveIn(BaseModel):
    decision: str  # approve | reject
    reason: str | None = None
    edited_args: dict | None = None
    approved_items: list[int] | None = None  # batch tools: which proposed items stay ticked


@router.get("/actions/{action_id}")
def get_action(request: Request, action_id: str) -> dict:
    return request.app.state.container.approvals.get(action_id)


@router.post("/approve/{action_id}")
async def approve(request: Request, action_id: str, body: ApproveIn) -> dict:
    """Approve or reject a pending action. The paused run resumes; a rejection is fed back to the agent as feedback."""
    c = request.app.state.container
    if body.decision not in ("approve", "reject"):
        raise AppError("BAD_DECISION", "decision must be 'approve' or 'reject'", 422)
    row = c.approvals.get(action_id)
    if body.edited_args is not None and body.decision == "approve":
        tool = c.registry.get(row["tool_name"])
        try:
            tool.input_model.model_validate(body.edited_args)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            raise AppError("BAD_EDITED_ARGS", f"Edited arguments are invalid: {str(exc)[:200]}", 422) from exc
    d = Decision(
        body.decision, body.reason, body.edited_args if body.decision == "approve" else None, body.approved_items
    )
    live = c.approvals.decide(action_id, d)
    resumed = False
    if not live and not c.runs.is_active(row["run_id"]):
        resumed = await c.runs.resume_orphan(row["run_id"], d)  # e.g. LangGraph run after a server restart
    return {
        "status": "approved" if body.decision == "approve" else "rejected",
        "resumed_from_checkpoint": resumed,
        "run_id": row["run_id"],
    }
