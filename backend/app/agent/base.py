"""Shared machinery for both runtimes. AgentCore = everything about ONE run except the control flow (loop vs graph)."""

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel, ValidationError

from app.adapters.llm import ChatLLM
from app.agent.events import RunBus
from app.agent.guardrails import LOOP_STOP_AT, register_action, wrap_untrusted
from app.agent.parser import PROTOCOL_HELP, Decision, ParseError, parse_decision, parse_plan
from app.agent.planner_prompt import build_plan_request, build_system_prompt
from app.config import Settings
from app.db.session import connect
from app.errors import AppError
from app.services.approval_service import ApprovalManager
from app.services.approval_service import Decision as Approval
from app.tools.base import Tool, ToolContext, ToolError, compact
from app.tools.registry import Registry

log = logging.getLogger(__name__)
MAX_REPAIRS = 2


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class RunContext:
    run_id: str
    task: str
    runtime: str
    settings: Settings
    registry: Registry
    llm: ChatLLM
    tool_ctx: ToolContext
    bus: RunBus
    approvals: ApprovalManager
    max_steps: int
    dry_run: bool = False
    use_plan: bool = False
    scope: dict = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)
    waited: float = 0.0  # seconds spent waiting for the human; does not count against the run timeout


@dataclass
class Prepared:
    status: str  # ok | observation | stop
    tool: Tool | None = None
    args: dict | None = None  # validated, JSON-able
    message: str | None = None  # text for the model (status=observation) or the reason (status=stop)
    code: str | None = None


class AgentRuntime(ABC):
    """One interface, two implementations (hand-written ReAct loop, LangGraph graph) so the UI can switch."""

    name: str

    def __init__(self, rc: RunContext) -> None:
        self.rc = rc
        self.core = AgentCore(rc)

    @abstractmethod
    async def run(self) -> None: ...


class AgentCore:
    def __init__(self, rc: RunContext) -> None:
        self.rc = rc
        self.s = rc.settings
        self.idx = self._next_idx()

    # ---------- persistence + events ----------
    def _next_idx(self) -> int:
        with connect(self.s.db_path) as con:
            return int(
                con.execute("SELECT COALESCE(MAX(idx),-1)+1 FROM steps WHERE run_id=?", (self.rc.run_id,)).fetchone()[0]
            )

    async def emit(
        self,
        event: str,
        data: dict,
        step_type: str | None = None,
        tool: str | None = None,
        tin=None,
        tout=None,
        error: str | None = None,
        ms: int | None = None,
    ) -> int | None:
        """Send an event to subscribers and, for steps, persist it (this is the replayable trace)."""
        step_id = None
        if step_type:
            with connect(self.s.db_path) as con:
                step_id = int(
                    con.execute(
                        "INSERT INTO steps(run_id,idx,type,tool_name,tool_input_json,tool_output_json,error,duration_ms,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            self.rc.run_id,
                            self.idx,
                            step_type,
                            tool,
                            json.dumps(tin) if tin is not None else None,
                            json.dumps(tout, default=str) if tout is not None else None,
                            error,
                            ms,
                            _now(),
                        ),
                    ).lastrowid
                )
            self.idx += 1
        await self.rc.bus.emit(event, data)
        return step_id

    def set_status(self, status: str, **cols) -> None:
        sets, vals = ["status=?"], [status]
        for k, v in cols.items():
            sets.append(f"{k}=?")
            vals.append(v)
        with connect(self.s.db_path) as con:
            con.execute(
                f"UPDATE runs SET {', '.join(sets)} WHERE id=?", (*vals, self.rc.run_id)
            )  # noqa: S608 - column names are ours

    # ---------- prompts ----------
    def memory(self) -> list[dict]:
        if self.s.memory_runs <= 0:
            return []
        with connect(self.s.db_path) as con:
            rows = con.execute(
                "SELECT r.task, s.summary FROM run_summaries s JOIN runs r ON r.id=s.run_id WHERE s.run_id != ? ORDER BY s.created_at DESC LIMIT ?",
                (self.rc.run_id, self.s.memory_runs),
            ).fetchall()
        return [{"task": r["task"][:120], "summary": r["summary"][:200]} for r in rows]

    def initial_messages(self) -> list[dict]:
        rc = self.rc
        scope = None
        if rc.scope.get("files") or rc.scope.get("folders"):
            scope = ", ".join([*rc.scope.get("files", []), *[f + "/" for f in rc.scope.get("folders", [])]])
        system = build_system_prompt(rc.registry, rc.max_steps, scope, rc.dry_run, self.memory())
        return [{"role": "system", "content": system}, {"role": "user", "content": f"Task: {rc.task}"}]

    # ---------- budgets ----------
    def run_timed_out(self) -> bool:
        return (time.monotonic() - self.rc.started - self.rc.waited) > self.s.agent_run_timeout_s

    # ---------- LLM ----------
    async def _chat(self, messages: list[dict], json_mode: bool = True) -> str:
        try:
            return await asyncio.wait_for(self.rc.llm.chat(messages, json_mode=json_mode), self.s.agent_step_timeout_s)
        except TimeoutError as exc:
            raise AppError(
                "LLM_TIMEOUT", f"The model did not answer within {self.s.agent_step_timeout_s:g}s", 504
            ) from exc

    async def plan(self) -> list[str]:
        """Optional first step: a numbered list of sub-goals shown to the user. A bad plan is skipped, never fatal."""
        try:
            steps = parse_plan(
                await self._chat(
                    [*self.initial_messages()[:1], {"role": "user", "content": build_plan_request(self.rc.task)}]
                )
            )
        except (ParseError, AppError):
            return []
        await self.emit("plan", {"steps": steps}, "plan", tout=steps)
        return steps

    async def decide(self, messages: list[dict]) -> Decision:
        """Ask the model for the next action; on malformed output show it the error and retry (repair) up to MAX_REPAIRS times."""
        convo = list(messages)
        last_err = ""
        for attempt in range(MAX_REPAIRS + 1):
            raw = await self._chat(convo)
            try:
                dec = parse_decision(raw)
                dec.raw = raw
                return dec
            except ParseError as exc:
                last_err = str(exc)
                log.info("llm_output_repair attempt=%d err=%s", attempt + 1, last_err)
                convo = [
                    *convo,
                    {"role": "assistant", "content": raw[:2000]},
                    {"role": "user", "content": f"Your reply was not valid: {last_err}. {PROTOCOL_HELP}"},
                ]
        raise AppError("BAD_LLM_OUTPUT", f"The model kept returning invalid output ({last_err})", 502)

    # ---------- validating + executing actions ----------
    def prepare(self, dec: Decision, counts: dict[str, int]) -> Prepared:
        tool = self.rc.registry.get(dec.tool or "")
        if tool is None:
            return Prepared(
                "observation",
                message=f"Unknown tool '{dec.tool}'. Valid tools: {', '.join(self.rc.registry.names())}. There is no delete tool.",
                code="UNKNOWN_TOOL",
            )
        try:
            args = tool.input_model.model_validate(dec.args or {}).model_dump()
        except ValidationError as exc:
            detail = "; ".join(f"{'.'.join(str(x) for x in e['loc']) or 'args'}: {e['msg']}" for e in exc.errors()[:5])
            return Prepared(
                "observation", tool=tool, message=f"Invalid arguments for {tool.name}: {detail}", code="BAD_ARGS"
            )
        verdict = register_action(counts, tool.name, args)
        if verdict == "stop":
            return Prepared(
                "stop",
                tool=tool,
                args=args,
                message=f"The agent repeated the same action {LOOP_STOP_AT} times",
                code="LOOP_DETECTED",
            )
        if verdict == "warn":
            return Prepared(
                "observation",
                tool=tool,
                args=args,
                code="REPEATED_ACTION",
                message="You repeated an action with identical arguments, so it was not run again. Try something different, or give your final answer.",
            )
        return Prepared("ok", tool=tool, args=args)

    def needs_approval(self, tool: Tool) -> bool:
        return tool.risk == "write" and not self.rc.dry_run and tool.kind in self.s.approval_kinds

    async def preview(self, tool: Tool, args: dict) -> dict:
        return await tool.preview(tool.input_model.model_validate(args), self.rc.tool_ctx)

    async def request_approval(
        self, tool: Tool, args: dict, preview: dict, step_id: int | None, action_id: str | None = None
    ) -> str:
        """Create the pending action and tell the UI. Idempotent per action_id: a LangGraph node that is replayed after a
        resume must not create a second request."""
        action_id = action_id or self.rc.approvals.new_id()
        if self.rc.approvals.exists(action_id):
            return action_id
        self.rc.approvals.create(self.rc.run_id, step_id, tool.name, args, tool.risk, preview, action_id)
        await self.emit(
            "approval_required",
            {"action_id": action_id, "tool": tool.name, "args": args, "risk": tool.risk, "preview": preview},
            "approval",
            tool.name,
            tin=args,
            tout={"status": "pending", "action_id": action_id, "preview": preview},
        )
        return action_id

    async def await_decision(self, action_id: str) -> Approval:
        t0 = time.monotonic()
        d = await self.rc.approvals.wait(action_id)
        self.rc.waited += time.monotonic() - t0
        return d

    async def apply_decision(
        self, tool: Tool, args: dict, action_id: str, d: Approval
    ) -> tuple[dict | None, str | None]:
        """Returns (effective_args, None) to run the tool, or (None, message_for_model) when rejected/invalid."""
        await self.emit(
            "approval_resolved",
            {
                "action_id": action_id,
                "decision": d.decision,
                "reason": d.reason,
                "edited": bool(d.edited_args),
                "approved_items": d.approved_items,
            },
            "approval",
            tool.name,
            tin=args,
            tout={"status": "approved" if d.decision == "approve" else "rejected", "reason": d.reason},
        )
        self.set_status("running")
        if d.decision != "approve":
            why = d.reason or ("no reason given" if not d.expired else "the approval expired")
            return None, f"User rejected this action: {why}. Do not repeat it; adjust your plan or finish and explain."
        eff = dict(args)
        if d.edited_args:
            try:
                eff = tool.input_model.model_validate(d.edited_args).model_dump()
            except ValidationError as exc:
                return (
                    None,
                    f"User approved but the edited arguments were invalid ({exc.errors()[0]['msg']}). The action was not run.",
                )
        if d.approved_items is not None and "moves" in eff:  # batch approval: keep only the ticked items
            eff["moves"] = [m for i, m in enumerate(eff["moves"]) if i in d.approved_items]
            if not eff["moves"]:
                return None, "User approved none of the proposed moves. Nothing was changed."
        return eff, None

    async def execute(self, tool: Tool, args: dict) -> dict:
        """Run (or, in dry-run mode, simulate) a tool. Never raises: errors become observations the agent can recover from."""
        t0 = time.perf_counter()
        parsed = tool.input_model.model_validate(args)
        try:
            if tool.risk == "write" and self.rc.dry_run:
                out = {
                    "dry_run": True,
                    "would": await asyncio.wait_for(
                        tool.preview(parsed, self.rc.tool_ctx), self.s.agent_step_timeout_s
                    ),
                }
            else:
                out = await asyncio.wait_for(tool.run(parsed, self.rc.tool_ctx), self.s.agent_step_timeout_s)
            return {
                "ok": True,
                "output": compact(out, self.s.max_tool_output_chars),
                "ms": int((time.perf_counter() - t0) * 1000),
            }
        except ToolError as exc:
            err = str(exc)
        except AppError as exc:
            err = exc.message
        except TimeoutError:
            err = f"{tool.name} timed out after {self.s.agent_step_timeout_s:g}s"
        except Exception as exc:  # noqa: BLE001
            log.exception("tool_crashed tool=%s", tool.name)
            err = f"{tool.name} failed unexpectedly ({type(exc).__name__})"
        return {"ok": False, "error": err, "ms": int((time.perf_counter() - t0) * 1000)}

    @staticmethod
    def observation_message(tool: str, result: dict) -> str:
        if result["ok"]:
            return wrap_untrusted(tool, json.dumps(result["output"], ensure_ascii=False, default=str))
        return f'Tool "{tool}" failed: {result["error"]}'

    # ---------- recording what happened ----------
    async def record_thought(self, dec: Decision, step: int) -> None:
        await self.emit("thought", {"text": dec.thought, "step": step}, "thought", tout={"text": dec.thought})

    async def record_action(self, dec: Decision, step: int, risk: str | None) -> None:
        await self.emit(
            "action", {"tool": dec.tool, "args": dec.args, "step": step, "risk": risk}, "action", dec.tool, tin=dec.args
        )

    async def record_observation(self, tool: str, result: dict, step: int, model_text: str | None = None) -> str:
        """Emit + persist an observation; returns the text that is sent back to the model."""
        data = {"tool": tool, "step": step, "duration_ms": result.get("ms")}
        data.update({"output": result["output"]} if result["ok"] else {"error": result["error"]})
        await self.emit(
            "observation",
            data,
            "observation",
            tool,
            tout=result.get("output"),
            error=result.get("error"),
            ms=result.get("ms"),
        )
        return model_text or self.observation_message(tool, result)

    async def record_note(self, tool: str, message: str, step: int) -> str:
        return await self.record_observation(tool, {"ok": False, "error": message, "ms": 0}, step, model_text=message)

    async def preview_or_error(self, tool: Tool, args: dict) -> tuple[dict | None, str | None]:
        """Preview a write action. Returns (preview, None) or (None, error message). Batch moves with no valid item are refused here."""
        try:
            preview = await self.preview(tool, args)
        except (ToolError, AppError) as exc:
            return None, str(getattr(exc, "message", exc))
        if preview.get("items") is not None and preview.get("ok_count") == 0:
            problems = "; ".join(f"{i['source']}: {i['problem']}" for i in preview["items"][:5])
            return None, f"None of the proposed changes is valid ({problems}). Nothing was changed."
        return preview, None

    # ---------- finishing ----------
    async def finish_completed(self, answer: str) -> None:
        arts = list(dict.fromkeys(self.rc.tool_ctx.artifacts))
        await self.emit(
            "final", {"answer": answer, "artifacts": arts}, "final", tout={"answer": answer, "artifacts": arts}
        )
        self.set_status("completed", finished_at=_now(), final_answer=answer)
        self._remember(answer, arts)

    async def finish_max_steps(self, steps: int) -> None:
        await self.emit("max_steps_reached", {"steps": steps})
        answer = (
            f"Stopped after {steps} steps without reaching a final answer. See the steps above for progress so far."
        )
        arts = list(dict.fromkeys(self.rc.tool_ctx.artifacts))
        await self.emit(
            "final",
            {"answer": answer, "artifacts": arts, "partial": True},
            "final",
            tout={"answer": answer, "artifacts": arts},
        )
        self.set_status("max_steps", finished_at=_now(), final_answer=answer)
        self._remember(answer, arts)

    async def finish_failed(self, code: str, message: str, status: str = "failed") -> None:
        await self.emit("error", {"code": code, "message": message}, "error", error=message, tout={"code": code})
        self.set_status(status, finished_at=_now(), error=f"{code}: {message}")
        self.rc.approvals.expire_for_run(self.rc.run_id)

    def _remember(self, answer: str, artifacts: list[str]) -> None:
        with connect(self.s.db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO run_summaries(run_id,summary,created_at) VALUES(?,?,?)",
                (self.rc.run_id, answer[:400], _now()),
            )
            con.execute(
                "INSERT INTO task_memory(run_id,key,value) VALUES(?,?,?)",
                (self.rc.run_id, "artifacts", json.dumps(artifacts)),
            )
            con.execute(
                "INSERT INTO task_memory(run_id,key,value) VALUES(?,?,?)", (self.rc.run_id, "steps", str(self.idx))
            )


def args_of(m: BaseModel) -> dict:
    return m.model_dump()
