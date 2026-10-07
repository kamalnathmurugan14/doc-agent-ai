"""Runtime B - the same agent as a LangGraph graph:  plan -> act -> (approval?) -> observe -> act ... -> END.

The approval node uses interrupt(): the graph STOPS, its state is checkpointed to SQLite, and it resumes with
Command(resume=decision) - even in a new process after a restart.
"""

import json
import logging

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.agent.base import AgentRuntime
from app.agent.state import GState
from app.errors import AppError
from app.services.approval_service import Decision as Approval

log = logging.getLogger(__name__)


class LangGraphRuntime(AgentRuntime):
    name = "langgraph"

    # ---------- graph ----------
    def build(self, checkpointer):
        core, rc = self.core, self.rc

        async def plan_node(state: GState) -> GState:
            msgs = list(state["messages"])
            if rc.use_plan:
                plan = await core.plan()
                if plan:
                    msgs += [
                        {"role": "assistant", "content": json.dumps({"plan": plan})},
                        {"role": "user", "content": "Plan noted. Begin with step 1."},
                    ]
            return {"messages": msgs}

        async def act_node(state: GState) -> GState:
            """THINK: ask the model; validate; decide whether the action needs a human."""
            try:
                steps = state.get("step_count", 0)
                if steps >= rc.max_steps:
                    await core.finish_max_steps(steps)
                    return {"done": True, "pending": None}
                if core.run_timed_out():
                    await core.finish_failed(
                        "RUN_TIMEOUT", f"The run exceeded {core.s.agent_run_timeout_s:g}s of active time"
                    )
                    return {"done": True, "pending": None}
                msgs, counts = list(state["messages"]), dict(state.get("counts") or {})
                dec = await core.decide(msgs)
                if dec.final:
                    await core.finish_completed(dec.final)
                    return {"done": True, "pending": None}
                step = steps + 1
                prepared = core.prepare(dec, counts)
                await core.record_thought(dec, step)
                await core.record_action(dec, step, prepared.tool.risk if prepared.tool else None)
                msgs.append({"role": "assistant", "content": dec.raw})
                base = {"messages": msgs, "counts": counts, "decision": None}
                if prepared.status == "stop":
                    await core.finish_failed(prepared.code or "LOOP_DETECTED", prepared.message or "loop detected")
                    return {**base, "done": True, "pending": None}
                if prepared.status == "observation":
                    return {
                        **base,
                        "pending": {"kind": "note", "tool": dec.tool or "?", "message": prepared.message, "step": step},
                    }
                tool, args = prepared.tool, prepared.args
                assert tool is not None and args is not None
                if core.needs_approval(tool):
                    preview, err = await core.preview_or_error(tool, args)
                    if err:
                        return {**base, "pending": {"kind": "note", "tool": tool.name, "message": err, "step": step}}
                    # the pending action is created in the approval node (after this node's state is checkpointed)
                    return {
                        **base,
                        "pending": {
                            "kind": "approval",
                            "tool": tool.name,
                            "args": args,
                            "action_id": core.rc.approvals.new_id(),
                            "preview": preview,
                            "step": step,
                        },
                    }
                return {**base, "pending": {"kind": "run", "tool": tool.name, "args": args, "step": step}}
            except AppError as exc:
                await core.finish_failed(exc.code, exc.message)
                return {"done": True, "pending": None}

        async def approval_node(state: GState) -> GState:
            p = state["pending"] or {}
            tool = rc.registry.get(p["tool"])
            assert tool is not None
            # idempotent: on resume this node re-runs from the top, but the request already exists, so nothing is duplicated
            await core.request_approval(tool, p["args"], p.get("preview") or {}, None, p["action_id"])
            decision = interrupt({"action_id": p.get("action_id"), "tool": p.get("tool"), "preview": p.get("preview")})
            return {"decision": decision}

        async def observe_node(state: GState) -> GState:
            """ACT + OBSERVE: execute the tool (or apply the human's decision) and feed the result back."""
            p = state["pending"] or {}
            msgs = list(state["messages"])
            step = p.get("step", state.get("step_count", 0) + 1)
            if p.get("kind") == "note":
                msgs.append({"role": "user", "content": await core.record_note(p["tool"], p["message"], step)})
            else:
                tool = rc.registry.get(p["tool"])
                assert tool is not None
                args = p["args"]
                rejection = None
                if p.get("kind") == "approval":
                    args2, rejection = await core.apply_decision(
                        tool, args, p["action_id"], Approval(**(state.get("decision") or {"decision": "reject"}))
                    )
                    args = args2 or args
                if rejection:
                    msgs.append({"role": "user", "content": await core.record_note(tool.name, rejection, step)})
                else:
                    msgs.append(
                        {
                            "role": "user",
                            "content": await core.record_observation(tool.name, await core.execute(tool, args), step),
                        }
                    )
            return {"messages": msgs, "step_count": state.get("step_count", 0) + 1, "pending": None, "decision": None}

        def after_plan(_: GState) -> str:
            return "act"

        def after_act(state: GState) -> str:
            if state.get("done"):
                return END
            return "approval" if (state.get("pending") or {}).get("kind") == "approval" else "observe"

        g = StateGraph(GState)
        g.add_node("plan", plan_node)
        g.add_node("act", act_node)
        g.add_node("approval", approval_node)
        g.add_node("observe", observe_node)
        g.add_edge(START, "plan")
        g.add_conditional_edges("plan", after_plan, {"act": "act"})
        g.add_conditional_edges("act", after_act, {"approval": "approval", "observe": "observe", END: END})
        g.add_edge("approval", "observe")
        g.add_edge("observe", "act")
        return g.compile(checkpointer=checkpointer)

    # ---------- driving ----------
    @property
    def _cfg(self) -> dict:
        return {"configurable": {"thread_id": self.rc.run_id}, "recursion_limit": 6 * self.rc.max_steps + 20}

    async def _drive(self, graph, first_input) -> None:
        """Run until the graph ends; each interrupt = wait for the human, then resume with Command(resume=...)."""
        inp = first_input
        while True:
            interrupted = None
            async for upd in graph.astream(
                inp, self._cfg, stream_mode="updates", durability="sync"
            ):  # sync: checkpoint is on disk before the next step
                if "__interrupt__" in upd:
                    interrupted = upd["__interrupt__"][0].value
            if interrupted is None:
                return
            decision = await self.core.await_decision(interrupted["action_id"])
            inp = Command(resume=decision.as_dict())

    async def run(self) -> None:
        async with AsyncSqliteSaver.from_conn_string(str(self.rc.settings.checkpoint_path)) as cp:
            graph = self.build(cp)
            await self._drive(
                graph,
                {
                    "messages": self.core.initial_messages(),
                    "step_count": 0,
                    "counts": {},
                    "pending": None,
                    "decision": None,
                    "done": False,
                },
            )

    async def resume(self, decision: Approval) -> None:
        """Continue a run whose process died while it was waiting for approval (state comes from the SQLite checkpoint)."""
        self.core.set_status("running")
        async with AsyncSqliteSaver.from_conn_string(str(self.rc.settings.checkpoint_path)) as cp:
            graph = self.build(cp)
            await self._drive(graph, Command(resume=decision.as_dict()))
