"""Runtime A - the hand-written ReAct loop: think -> act -> observe, repeated until a final answer or the step budget runs out."""

import json
import logging

from app.agent.base import AgentRuntime
from app.errors import AppError

log = logging.getLogger(__name__)


class ReActRuntime(AgentRuntime):
    name = "react"

    async def run(self) -> None:
        core, rc = self.core, self.rc
        messages = core.initial_messages()
        counts: dict[str, int] = {}
        steps = 0
        try:
            if rc.use_plan:
                plan = await core.plan()
                if plan:
                    messages += [
                        {"role": "assistant", "content": json.dumps({"plan": plan})},
                        {"role": "user", "content": "Plan noted. Begin with step 1."},
                    ]
            while steps < rc.max_steps:
                if core.run_timed_out():
                    await core.finish_failed(
                        "RUN_TIMEOUT", f"The run exceeded {core.s.agent_run_timeout_s:g}s of active time"
                    )
                    return
                dec = await core.decide(messages)  # 1) THINK: the model proposes the next action (or the final answer)
                if dec.final:
                    await core.finish_completed(dec.final)
                    return
                step = steps + 1
                prepared = core.prepare(dec, counts)
                await core.record_thought(dec, step)
                await core.record_action(dec, step, prepared.tool.risk if prepared.tool else None)
                messages.append({"role": "assistant", "content": dec.raw})
                if prepared.status == "stop":
                    await core.finish_failed(prepared.code or "LOOP_DETECTED", prepared.message or "loop detected")
                    return
                if (
                    prepared.status == "observation"
                ):  # unknown tool / bad args / repeated action: tell the model and let it recover
                    messages.append(
                        {
                            "role": "user",
                            "content": await core.record_note(dec.tool or "?", prepared.message or "", step),
                        }
                    )
                    steps += 1
                    continue
                tool, args = prepared.tool, prepared.args
                assert tool is not None and args is not None
                if core.needs_approval(tool):  # 2) human-in-the-loop: pause until approve / reject
                    preview, err = await core.preview_or_error(tool, args)
                    if err:
                        messages.append({"role": "user", "content": await core.record_note(tool.name, err, step)})
                        steps += 1
                        continue
                    action_id = await core.request_approval(tool, args, preview or {}, None)
                    decision = await core.await_decision(action_id)
                    args2, rejection = await core.apply_decision(tool, args, action_id, decision)
                    if rejection:
                        messages.append({"role": "user", "content": await core.record_note(tool.name, rejection, step)})
                        steps += 1
                        continue
                    args = args2 or args
                result = await core.execute(tool, args)  # 3) ACT, then 4) OBSERVE
                messages.append({"role": "user", "content": await core.record_observation(tool.name, result, step)})
                steps += 1
            await core.finish_max_steps(steps)
        except AppError as exc:
            await core.finish_failed(exc.code, exc.message)
