"""Starts runs as background tasks (a closed browser tab does not kill a run), tracks them, cancels them, resumes orphans."""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.adapters.classifier import Classifier
from app.adapters.llm import ChatLLM
from app.adapters.retriever import Retriever
from app.agent.base import AgentRuntime, RunContext
from app.agent.events import RunBus
from app.agent.graph import LangGraphRuntime
from app.agent.react_loop import ReActRuntime
from app.config import Settings
from app.core.paths import ext_of, rel_posix, safe_resolve
from app.db.session import connect
from app.errors import AppError
from app.services.approval_service import ApprovalManager, Decision
from app.tools.base import ToolContext
from app.tools.registry import Registry

log = logging.getLogger(__name__)
RUNTIMES: dict[str, type[AgentRuntime]] = {"react": ReActRuntime, "langgraph": LangGraphRuntime}


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class LiveRun:
    run_id: str
    bus: RunBus = field(default_factory=RunBus)
    task: asyncio.Task | None = None
    runtime: AgentRuntime | None = None


class RunManager:
    def __init__(
        self,
        settings: Settings,
        registry: Registry,
        llm: ChatLLM,
        retriever: Retriever,
        classifier: Classifier,
        approvals: ApprovalManager,
    ) -> None:
        self.s, self.registry, self.llm, self.retriever, self.classifier, self.approvals = (
            settings,
            registry,
            llm,
            retriever,
            classifier,
            approvals,
        )
        self.live: dict[str, LiveRun] = {}

    # ---------- creation ----------
    def _clean_scope(self, scope: dict | None) -> dict:
        out: dict = {"files": [], "folders": []}
        for key in ("files", "folders"):
            for p in (scope or {}).get(key, []) or []:
                path = safe_resolve(self.s.docs_root, p.rstrip("/"))
                if key == "files" and (not path.is_file() or ext_of(path.name) not in self.s.extensions):
                    raise AppError("BAD_SCOPE", f"Scope file not found or unsupported: {p}", 422)
                if key == "folders" and not path.is_dir():
                    raise AppError("BAD_SCOPE", f"Scope folder not found: {p}", 422)
                out[key].append(rel_posix(self.s.docs_root, path))
        return out

    def _context(
        self,
        run_id: str,
        task: str,
        runtime: str,
        scope: dict,
        dry_run: bool,
        max_steps: int,
        use_plan: bool,
        bus: RunBus,
    ) -> RunContext:
        tctx = ToolContext(
            self.s,
            self.retriever,
            self.classifier,
            self.llm,
            scope_files=scope["files"] or None,
            scope_folders=scope["folders"],
            dry_run=dry_run,
        )
        return RunContext(
            run_id,
            task,
            runtime,
            self.s,
            self.registry,
            self.llm,
            tctx,
            bus,
            self.approvals,
            max_steps,
            dry_run,
            use_plan,
            scope,
        )

    async def start(
        self,
        task: str,
        runtime: str = "react",
        scope: dict | None = None,
        max_steps: int | None = None,
        dry_run: bool = False,
        plan: bool = False,
    ) -> LiveRun:
        task = task.strip()
        if not task:
            raise AppError("EMPTY_TASK", "Task must not be empty", 422)
        if runtime not in RUNTIMES:
            raise AppError("BAD_RUNTIME", f"runtime must be one of {', '.join(RUNTIMES)}", 422)
        steps = self.s.agent_max_steps if max_steps is None else max_steps
        if not 1 <= steps <= 50:
            raise AppError("BAD_MAX_STEPS", "max_steps must be between 1 and 50", 422)
        clean = self._clean_scope(scope)
        run_id = "run_" + uuid.uuid4().hex[:10]
        with connect(self.s.db_path) as con:
            con.execute(
                "INSERT INTO runs(id,task,status,runtime,model,dry_run,scope_json,started_at) VALUES(?,?,?,?,?,?,?,?)",
                (run_id, task, "running", runtime, self.llm.model, int(dry_run), json.dumps(clean), now()),
            )
        live = LiveRun(run_id)
        rc = self._context(run_id, task, runtime, clean, dry_run, steps, plan, live.bus)
        live.runtime = RUNTIMES[runtime](rc)
        self.live[run_id] = live
        live.task = asyncio.create_task(self._execute(live, live.runtime.run(), rc))
        return live

    # ---------- execution ----------
    async def _execute(self, live: LiveRun, coro, rc: RunContext, announce: bool = True) -> None:
        core = live.runtime.core  # type: ignore[union-attr]
        try:
            if announce:
                await live.bus.emit(
                    "run_started",
                    {
                        "run_id": rc.run_id,
                        "task": rc.task,
                        "runtime": rc.runtime,
                        "model": self.llm.model,
                        "dry_run": rc.dry_run,
                        "max_steps": rc.max_steps,
                        "plan": rc.use_plan,
                    },
                )
            await coro
        except asyncio.CancelledError:
            await core.finish_failed("CANCELLED", "The run was cancelled", status="cancelled")
        except AppError as exc:
            await core.finish_failed(exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001
            log.exception("run_crashed run=%s", rc.run_id)
            await core.finish_failed("INTERNAL_ERROR", f"Unexpected error ({type(exc).__name__})")
        finally:
            await live.bus.close()

    def cancel(self, run_id: str) -> bool:
        live = self.live.get(run_id)
        if live and live.task and not live.task.done():
            live.task.cancel()
            return True
        return False

    def is_active(self, run_id: str) -> bool:
        live = self.live.get(run_id)
        return bool(live and live.task and not live.task.done())

    async def resume_orphan(self, run_id: str, decision: Decision) -> bool:
        """The process that owned this run is gone. LangGraph runs can continue from their SQLite checkpoint."""
        run = self.get_row(run_id)
        if run["runtime"] != "langgraph" or run["status"] != "waiting_approval":
            return False
        scope = json.loads(run["scope_json"])
        live = LiveRun(run_id)
        rc = self._context(
            run_id, run["task"], "langgraph", scope, bool(run["dry_run"]), self.s.agent_max_steps, False, live.bus
        )
        rt = LangGraphRuntime(rc)
        live.runtime = rt
        self.live[run_id] = live
        live.task = asyncio.create_task(self._execute(live, rt.resume(decision), rc, announce=False))
        return True

    def recover(self) -> int:
        """At startup: ReAct runs that were in flight cannot continue (their loop lived in memory) -> mark failed."""
        with connect(self.s.db_path) as con:
            rows = con.execute(
                "SELECT id FROM runs WHERE status IN ('running','waiting_approval') AND runtime='react'"
            ).fetchall()
            for r in rows:
                con.execute(
                    "UPDATE runs SET status='failed', finished_at=?, error='INTERRUPTED: the server restarted while this run was active' WHERE id=?",
                    (now(), r["id"]),
                )
                con.execute(
                    "UPDATE pending_actions SET status='expired' WHERE run_id=? AND status='pending'", (r["id"],)
                )
        return len(rows)

    # ---------- reads ----------
    def get_row(self, run_id: str):
        with connect(self.s.db_path) as con:
            r = con.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if r is None:
            raise AppError("RUN_NOT_FOUND", "Run not found", 404)
        return r

    @staticmethod
    def _summary(r) -> dict:
        return {
            "id": r["id"],
            "task": r["task"],
            "status": r["status"],
            "runtime": r["runtime"],
            "model": r["model"],
            "dry_run": bool(r["dry_run"]),
            "started_at": r["started_at"],
            "finished_at": r["finished_at"],
            "final_answer": r["final_answer"],
            "error": r["error"],
        }

    def list_runs(self, status: str = "", limit: int = 50) -> list[dict]:
        with connect(self.s.db_path) as con:
            rows = con.execute(
                "SELECT * FROM runs WHERE (?='' OR status=?) ORDER BY started_at DESC, rowid DESC LIMIT ?",
                (status, status, limit),
            ).fetchall()
        return [self._summary(r) for r in rows]

    def trace(self, run_id: str) -> dict:
        r = self.get_row(run_id)
        with connect(self.s.db_path) as con:
            steps = con.execute("SELECT * FROM steps WHERE run_id=? ORDER BY idx", (run_id,)).fetchall()
            mem = con.execute("SELECT key, value FROM task_memory WHERE run_id=?", (run_id,)).fetchall()
        return {
            **self._summary(r),
            "scope": json.loads(r["scope_json"]),
            "steps": [
                {
                    "idx": s["idx"],
                    "type": s["type"],
                    "tool_name": s["tool_name"],
                    "tool_input": json.loads(s["tool_input_json"]) if s["tool_input_json"] else None,
                    "tool_output": json.loads(s["tool_output_json"]) if s["tool_output_json"] else None,
                    "error": s["error"],
                    "duration_ms": s["duration_ms"],
                    "created_at": s["created_at"],
                }
                for s in steps
            ],
            "pending_actions": self.approvals.pending_for_run(run_id),
            "memory": {m["key"]: m["value"] for m in mem},
        }
