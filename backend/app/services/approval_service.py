"""Pending actions: persisted in SQLite, and a future per action so a paused run can await the human's decision."""

import asyncio
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from app.config import Settings
from app.db.session import connect
from app.errors import AppError


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Decision:
    decision: str  # approve | reject
    reason: str | None = None
    edited_args: dict | None = None
    approved_items: list[int] | None = None  # batch tools: indexes of the items the user left ticked
    expired: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


class ApprovalManager:
    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self._waiters: dict[str, asyncio.Future] = {}

    @staticmethod
    def new_id() -> str:
        return "act_" + uuid.uuid4().hex[:10]

    def exists(self, action_id: str) -> bool:
        with connect(self.s.db_path) as con:
            return con.execute("SELECT 1 FROM pending_actions WHERE id=?", (action_id,)).fetchone() is not None

    def create(
        self,
        run_id: str,
        step_id: int | None,
        tool: str,
        args: dict,
        risk: str,
        preview: dict,
        action_id: str | None = None,
    ) -> str:
        action_id = action_id or self.new_id()
        with connect(self.s.db_path) as con:
            con.execute(
                "INSERT INTO pending_actions(id,run_id,step_id,tool_name,args_json,risk,preview_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (action_id, run_id, step_id, tool, json.dumps(args), risk, json.dumps(preview), now()),
            )
            con.execute("UPDATE runs SET status='waiting_approval' WHERE id=?", (run_id,))
        return action_id

    def get(self, action_id: str) -> dict:
        with connect(self.s.db_path) as con:
            r = con.execute("SELECT * FROM pending_actions WHERE id=?", (action_id,)).fetchone()
        if r is None:
            raise AppError("ACTION_NOT_FOUND", "Unknown action id", 404)
        d = dict(r)
        d["args"], d["preview"] = json.loads(d.pop("args_json")), json.loads(d.pop("preview_json"))
        d["decision"] = json.loads(d.pop("decision_json")) if d["decision_json"] else None
        return d

    def pending_for_run(self, run_id: str) -> list[dict]:
        with connect(self.s.db_path) as con:
            ids = [
                r["id"]
                for r in con.execute("SELECT id FROM pending_actions WHERE run_id=? AND status='pending'", (run_id,))
            ]
        return [self.get(i) for i in ids]

    async def wait(self, action_id: str) -> Decision:
        """Block until decide() is called or the approval expires (expiry counts as a rejection)."""
        row = self.get(action_id)
        if row["status"] != "pending":  # already decided (e.g. resumed after restart)
            return Decision(**(row["decision"] or {"decision": "reject", "reason": row["status"]}))
        fut = self._waiters.setdefault(action_id, asyncio.get_running_loop().create_future())
        try:
            return await asyncio.wait_for(asyncio.shield(fut), self.s.approval_timeout_s)
        except TimeoutError:
            self._finish(action_id, "expired", Decision("reject", "approval timed out", expired=True))
            return Decision("reject", "approval timed out", expired=True)
        finally:
            self._waiters.pop(action_id, None)

    def decide(self, action_id: str, d: Decision) -> bool:
        """Record the decision. Returns True if a live run was waiting (False = orphaned, e.g. after a restart)."""
        row = self.get(action_id)
        if row["status"] != "pending":
            raise AppError("ALREADY_DECIDED", f"This action was already {row['status']}", 409)
        self._finish(action_id, "approved" if d.decision == "approve" else "rejected", d)
        fut = self._waiters.get(action_id)
        if fut and not fut.done():
            fut.set_result(d)
            return True
        return False

    def _finish(self, action_id: str, status: str, d: Decision) -> None:
        with connect(self.s.db_path) as con:
            con.execute(
                "UPDATE pending_actions SET status=?, decision_json=?, decided_at=? WHERE id=?",
                (status, json.dumps(d.as_dict()), now(), action_id),
            )

    def expire_for_run(self, run_id: str) -> None:
        with connect(self.s.db_path) as con:
            ids = [
                r["id"]
                for r in con.execute("SELECT id FROM pending_actions WHERE run_id=? AND status='pending'", (run_id,))
            ]
        for i in ids:
            self._finish(i, "expired", Decision("reject", "run ended", expired=True))
            fut = self._waiters.get(i)
            if fut and not fut.done():
                fut.set_result(Decision("reject", "run ended", expired=True))
