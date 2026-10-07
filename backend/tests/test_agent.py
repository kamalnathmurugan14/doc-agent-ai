import asyncio
import json

import pytest

from app.db.session import connect
from app.services.approval_service import Decision
from tests.conftest import ScriptedLLM, act, final, kinds, last, run_agent

RUNTIMES = ["react", "langgraph"]
approve = lambda d: Decision("approve")  # noqa: E731
reject = lambda reason=None: (lambda d: Decision("reject", reason))  # noqa: E731


def status_of(container, run_id):
    return container.runs.get_row(run_id)["status"]


@pytest.mark.parametrize("rt", RUNTIMES)
def test_read_only_run_event_order_and_trace(container, llm, rt):
    llm.replies = [
        act("list_files", path="invoices"),
        act("read_file", path="invoices/feb.txt"),
        final("Two invoices; feb totals $440."),
    ]
    events, rid = run_agent(container, "What invoices do I have?", rt)
    assert kinds(events) == [
        "run_started",
        "thought",
        "action",
        "observation",
        "thought",
        "action",
        "observation",
        "final",
    ]
    assert events[0][1]["runtime"] == rt and events[0][1]["max_steps"] == 8
    assert events[2][1] == {"tool": "list_files", "args": {"path": "invoices"}, "step": 1, "risk": "read"}
    assert "invoices/feb.txt" in json.dumps(events[3][1]["output"]) and events[3][1]["duration_ms"] >= 0
    assert last(events, "final") == {"answer": "Two invoices; feb totals $440.", "artifacts": []}
    trace = container.runs.trace(rid)
    assert trace["status"] == "completed" and trace["final_answer"].startswith("Two invoices")
    assert [s["type"] for s in trace["steps"]] == [
        "thought",
        "action",
        "observation",
        "thought",
        "action",
        "observation",
        "final",
    ]
    assert [s["idx"] for s in trace["steps"]] == list(range(7)) and trace["steps"][1]["tool_input"] == {
        "path": "invoices"
    }
    # the model saw the document text only inside the untrusted wrapper
    obs_msg = llm.calls[1]["messages"][-1]["content"]
    assert obs_msg.startswith('Observation from tool "list_files"') and "<untrusted_data>" in obs_msg


@pytest.mark.parametrize("rt", RUNTIMES)
def test_system_prompt_lists_tools_and_rules(container, llm, rt):
    run_agent(container, "hello", rt)
    system = llm.calls[0]["messages"][0]["content"]
    for name in container.registry.names():
        assert f"**{name}**" in system
    assert (
        "NO delete tool" in system
        and "untrusted" in system
        and "at most 8 tool calls" in system
        and "final_answer" in system
    )
    assert (
        llm.calls[0]["messages"][1] == {"role": "user", "content": "Task: hello"} and llm.calls[0]["json_mode"] is True
    )


@pytest.mark.parametrize("rt", RUNTIMES)
def test_malformed_output_is_repaired(container, llm, rt):
    llm.replies = [
        "I think I should list files",
        '{"thought": "x", "action": {"tool": "list_files"',
        act("list_files"),
        final("ok"),
    ]
    events, rid = run_agent(container, "t", rt)
    assert kinds(events).count("action") == 1 and status_of(container, rid) == "completed"
    repair = llm.calls[1]["messages"][-1]["content"]
    assert "not valid" in repair and "Reply with exactly ONE JSON object" in repair
    assert llm.calls[2]["messages"][-2]["content"].startswith('{"thought"')  # the bad reply is shown back to the model


@pytest.mark.parametrize("rt", RUNTIMES)
def test_hopeless_output_fails_cleanly(container, llm, rt):
    llm.replies = ["nope"]
    events, rid = run_agent(container, "t", rt)
    assert last(events, "error")["code"] == "BAD_LLM_OUTPUT" and len(llm.calls) == 3  # 1 try + 2 repairs
    assert status_of(container, rid) == "failed"


@pytest.mark.parametrize("rt", RUNTIMES)
def test_unknown_tool_and_bad_args_get_corrective_observations(container, llm, rt):
    llm.replies = [
        act("delete_file", path="root.txt"),
        act("read_file"),
        act("read_file", path="root.txt", max_chars=5),
        final("gave up"),
    ]
    events, rid = run_agent(container, "t", rt)
    obs = [d for k, d in events if k == "observation"]
    assert (
        "Unknown tool 'delete_file'" in obs[0]["error"]
        and "list_files" in obs[0]["error"]
        and "no delete tool" in obs[0]["error"]
    )
    assert "Invalid arguments for read_file: path" in obs[1]["error"] and "Field required" in obs[1]["error"]
    assert "max_chars" in obs[2]["error"]
    assert (container.settings.docs_root / "root.txt").exists() and status_of(container, rid) == "completed"


@pytest.mark.parametrize("rt", RUNTIMES)
def test_tool_error_is_an_observation_and_agent_recovers(container, llm, rt):
    llm.replies = [act("read_file", path="../../etc/passwd"), act("read_file", path="root.txt"), final("recovered")]
    events, _ = run_agent(container, "t", rt)
    obs = [d for k, d in events if k == "observation"]
    assert "not allowed" in obs[0]["error"] and "output" in obs[1] and last(events, "final")["answer"] == "recovered"


@pytest.mark.parametrize("rt", RUNTIMES)
def test_loop_detection_warns_then_stops(container, llm, rt):
    llm.replies = [act("read_file", path="root.txt")]  # the model repeats itself forever
    events, rid = run_agent(container, "t", rt)
    obs = [d for k, d in events if k == "observation"]
    assert "output" in obs[0] and "repeated an action" in obs[1]["error"]  # 2nd identical call is NOT executed
    assert last(events, "error")["code"] == "LOOP_DETECTED" and "3 times" in last(events, "error")["message"]
    assert status_of(container, rid) == "failed" and len(obs) == 2
    assert "Try something different" in llm.calls[2]["messages"][-1]["content"]


@pytest.mark.parametrize("rt", RUNTIMES)
def test_max_steps(container, llm, rt):
    n = iter(range(100))
    llm.replies = lambda m: act("list_files", path="", pattern=f"p{next(n)}")  # always a new action
    events, rid = run_agent(container, "t", rt, max_steps=3)
    assert kinds(events).count("action") == 3 and "max_steps_reached" in kinds(events)
    assert (
        last(events, "max_steps_reached") == {"steps": 3} and "Stopped after 3 steps" in last(events, "final")["answer"]
    )
    assert status_of(container, rid) == "max_steps"


@pytest.mark.parametrize("rt", RUNTIMES)
def test_write_requires_approval_and_pauses(container, llm, rt, docs):
    llm.replies = [act("write_report", title="Invoice report", content="Total: $1,440"), final("Report written.")]
    seen = {}

    def decide(d):
        seen["status_while_waiting"] = status_of(container, rid_holder[0]) if rid_holder else None
        seen["file_exists_before"] = (docs / "_reports" / "invoice-report.md").exists()
        seen["preview"] = d["preview"]
        return Decision("approve")

    rid_holder: list = []

    async def go():
        live = await container.runs.start("report", rt)
        rid_holder.append(live.run_id)
        evs = []
        async for ev in live.bus.subscribe():
            evs.append((ev["event"], ev["data"]))
            if ev["event"] == "approval_required":
                container.approvals.decide(ev["data"]["action_id"], decide(ev["data"]))
        return evs

    events = asyncio.run(go())
    assert seen["status_while_waiting"] == "waiting_approval" and seen["file_exists_before"] is False
    assert seen["preview"]["destination"] == "_reports/invoice-report.md" and "Total" in seen["preview"]["content_head"]
    assert kinds(events) == [
        "run_started",
        "thought",
        "action",
        "approval_required",
        "approval_resolved",
        "observation",
        "final",
    ]
    assert (docs / "_reports" / "invoice-report.md").exists() and last(events, "final")["artifacts"] == [
        "_reports/invoice-report.md"
    ]
    row = container.approvals.get(events[3][1]["action_id"])
    assert row["status"] == "approved" and row["tool_name"] == "write_report" and row["decided_at"]


@pytest.mark.parametrize("rt", RUNTIMES)
def test_rejection_is_fed_back_and_nothing_changes(container, llm, rt, docs):
    llm.replies = [
        act("move_file", moves=[{"source": "root.txt", "destination": "archive/"}]),
        final("Understood, left the file alone."),
    ]
    events, rid = run_agent(container, "organize", rt, decide=reject("keep it where it is"))
    assert (docs / "root.txt").exists() and not (docs / "archive").exists()
    resolved = last(events, "approval_resolved")
    assert resolved["decision"] == "reject" and resolved["reason"] == "keep it where it is"
    assert "User rejected this action: keep it where it is" in llm.calls[1]["messages"][-1]["content"]
    assert last(events, "final")["answer"].startswith("Understood") and status_of(container, rid) == "completed"
    assert container.runs.trace(rid)["steps"][3]["type"] == "approval"


@pytest.mark.parametrize("rt", RUNTIMES)
def test_batch_approval_with_per_item_selection(container, llm, rt, docs):
    moves = [
        {"source": "invoices/jan.txt", "destination": "Invoices/2026/"},
        {"source": "invoices/feb.txt", "destination": "Invoices/2026/"},
        {"source": "notes/ideas.txt", "destination": "Notes/"},
    ]
    llm.replies = [act("move_file", moves=moves), final("moved some")]
    events, _ = run_agent(container, "organize", rt, decide=lambda d: Decision("approve", approved_items=[0, 2]))
    req = last(events, "approval_required")
    assert [i["ok"] for i in req["preview"]["items"]] == [True, True, True] and req["preview"]["ok_count"] == 3
    assert (docs / "Invoices" / "2026" / "jan.txt").exists() and (
        docs / "invoices" / "feb.txt"
    ).exists()  # item 1 left unticked
    assert (docs / "Notes" / "ideas.txt").exists()
    out = [d for k, d in events if k == "observation"][-1]["output"]
    assert out["moved"] == 2


@pytest.mark.parametrize("rt", RUNTIMES)
def test_edited_arguments_are_used_and_validated(container, llm, rt, docs):
    llm.replies = [act("rename_file", path="root.txt", new_name="draft.txt"), final("ok")]
    events, _ = run_agent(
        container,
        "t",
        rt,
        decide=lambda d: Decision("approve", edited_args={"path": "root.txt", "new_name": "budget.txt"}),
    )
    assert (
        (docs / "budget.txt").exists()
        and not (docs / "draft.txt").exists()
        and last(events, "approval_resolved")["edited"] is True
    )
    llm.replies = [act("rename_file", path="budget.txt", new_name="x.txt"), final("ok")]
    events, _ = run_agent(
        container,
        "t",
        rt,
        decide=lambda d: Decision("approve", edited_args={"path": "budget.txt", "new_name": "../evil.txt"}),
    )
    assert (docs / "budget.txt").exists() and "edited arguments were invalid" in llm.calls[-1]["messages"][-1][
        "content"
    ]


@pytest.mark.parametrize("rt", RUNTIMES)
def test_invalid_batch_is_refused_without_asking_the_human(container, llm, rt, docs):
    llm.replies = [
        act("move_file", moves=[{"source": "root.txt", "destination": "../../outside.txt"}]),
        final("could not"),
    ]
    events, _ = run_agent(container, "t", rt, decide=approve)
    assert (
        "approval_required" not in kinds(events)
        and "None of the proposed changes is valid" in [d for k, d in events if k == "observation"][0]["error"]
    )
    assert (docs / "root.txt").exists()


@pytest.mark.parametrize("rt", RUNTIMES)
def test_approval_expiry_counts_as_rejection(container, llm, rt, settings, docs):
    settings.approval_timeout_s = 0.05
    llm.replies = [act("rename_file", path="root.txt", new_name="late.txt"), final("expired")]
    events, rid = run_agent(container, "t", rt)  # nobody answers
    assert last(events, "approval_resolved")["decision"] == "reject" and (docs / "root.txt").exists()
    assert "approval timed out" in llm.calls[1]["messages"][-1]["content"]
    assert container.approvals.get(last(events, "approval_required")["action_id"])["status"] == "expired"


@pytest.mark.parametrize("rt", RUNTIMES)
def test_dry_run_simulates_writes_without_approval(container, llm, rt, docs):
    llm.replies = [
        act("write_report", title="R", content="body"),
        act("move_file", moves=[{"source": "root.txt", "destination": "x/"}]),
        final("would do both"),
    ]
    events, rid = run_agent(container, "t", rt, dry_run=True)
    assert "approval_required" not in kinds(events)
    obs = [d["output"] for k, d in events if k == "observation"]
    assert (
        obs[0]["dry_run"] is True
        and obs[0]["would"]["destination"] == "_reports/r.md"
        and obs[1]["would"]["items"][0]["ok"] is True
    )
    assert not (docs / "_reports").exists() and (docs / "root.txt").exists() and not (docs / "x").exists()
    assert "Dry-run mode" in llm.calls[0]["messages"][0]["content"] and container.runs.trace(rid)["dry_run"] is True


@pytest.mark.parametrize("rt", RUNTIMES)
def test_require_approval_setting_is_honoured(container, llm, rt, settings, docs):
    settings.require_approval = "move,rename"  # writes of reports no longer need approval
    llm.replies = [act("write_report", title="Free", content="x"), final("done")]
    events, _ = run_agent(container, "t", rt)
    assert "approval_required" not in kinds(events) and (docs / "_reports" / "free.md").exists()
    settings.require_approval = ""
    llm.replies = [act("rename_file", path="root.txt", new_name="n.txt"), final("done")]
    run_agent(container, "t", rt)
    assert (docs / "n.txt").exists()  # the user's explicit choice; guardrails still apply


@pytest.mark.parametrize("rt", RUNTIMES)
def test_scope_is_enforced_and_announced(container, llm, rt):
    llm.replies = [act("read_file", path="notes/ideas.txt"), final("blocked")]
    events, _ = run_agent(container, "t", rt, scope={"folders": ["invoices"]})
    assert "outside the scope" in [d for k, d in events if k == "observation"][0]["error"]
    assert (
        "invoices/" in llm.calls[0]["messages"][0]["content"]
        and "restricted this task" in llm.calls[0]["messages"][0]["content"]
    )


def test_bad_scope_rejected(container):
    for scope in ({"files": ["nope.txt"]}, {"folders": ["nope"]}, {"files": ["../../etc/passwd"]}):
        with pytest.raises(Exception) as e:
            run_agent(container, "t", scope=scope)
        assert getattr(e.value, "status", 0) in (400, 422)


@pytest.mark.parametrize("rt", RUNTIMES)
def test_llm_timeout_fails_the_run(container, llm, rt, settings):
    settings.agent_step_timeout_s = 0.05
    llm.delay = 1.0
    events, rid = run_agent(container, "t", rt)
    assert last(events, "error")["code"] == "LLM_TIMEOUT" and status_of(container, rid) == "failed"


@pytest.mark.parametrize("rt", RUNTIMES)
def test_run_timeout(container, llm, rt, settings):
    settings.agent_run_timeout_s = -1  # already exceeded
    events, rid = run_agent(container, "t", rt)
    assert last(events, "error")["code"] == "RUN_TIMEOUT" and llm.calls == []


@pytest.mark.parametrize("rt", RUNTIMES)
def test_tool_timeout_becomes_observation(container, llm, rt, settings, monkeypatch):
    settings.agent_step_timeout_s = 0.05

    async def slow(self, args, ctx):
        await asyncio.sleep(1)

    monkeypatch.setattr("app.tools.read_tools.ListFiles.run", slow)
    llm.replies = [act("list_files"), final("moved on")]
    events, _ = run_agent(container, "t", rt)
    assert (
        "timed out" in [d for k, d in events if k == "observation"][0]["error"]
        and last(events, "final")["answer"] == "moved on"
    )


@pytest.mark.parametrize("rt", RUNTIMES)
def test_unexpected_tool_crash_is_contained(container, llm, rt, monkeypatch):
    async def boom(self, args, ctx):
        raise RuntimeError("kaboom")

    monkeypatch.setattr("app.tools.read_tools.ListFiles.run", boom)
    llm.replies = [act("list_files"), final("survived")]
    events, _ = run_agent(container, "t", rt)
    assert "failed unexpectedly (RuntimeError)" in [d for k, d in events if k == "observation"][0][
        "error"
    ] and "kaboom" not in json.dumps(events)


@pytest.mark.parametrize("rt", RUNTIMES)
def test_planning_step(container, llm, rt):
    llm.replies = ['{"plan": ["1. list invoices", "2. total them"]}', final("planned")]
    events, rid = run_agent(container, "t", rt, plan=True)
    assert kinds(events)[:2] == ["run_started", "plan"] and events[1][1]["steps"] == [
        "1. list invoices",
        "2. total them",
    ]
    assert (
        "plan" in llm.calls[0]["messages"][-1]["content"].lower()
        and container.runs.trace(rid)["steps"][0]["type"] == "plan"
    )
    llm.replies = ["not a plan", final("still fine")]  # a broken plan is skipped, not fatal
    events, _ = run_agent(container, "t", rt, plan=True)
    assert "plan" not in kinds(events) and last(events, "final")["answer"] == "still fine"


@pytest.mark.parametrize("rt", RUNTIMES)
def test_memory_of_previous_tasks(container, llm, rt, settings):
    llm.replies = [final("Found 2 invoices totalling $1,440.")]
    run_agent(container, "Total my invoices", rt)
    run_agent(container, "second task", rt)
    system = llm.calls[-1]["messages"][0]["content"]
    assert "Recent tasks" in system and "Total my invoices -> Found 2 invoices" in system
    settings.memory_runs = 0
    run_agent(container, "third", rt)
    assert "Recent tasks" not in llm.calls[-1]["messages"][0]["content"]


@pytest.mark.parametrize("rt", RUNTIMES)
def test_cancel_running_and_waiting_runs(container, llm, rt):
    llm.delay = 5

    async def go():
        live = await container.runs.start("t", rt)
        await asyncio.sleep(0.1)
        assert container.runs.cancel(live.run_id) is True
        evs = [ev["event"] async for ev in live.bus.subscribe()]
        return evs, live.run_id

    evs, rid = asyncio.run(go())
    assert "error" in evs and status_of(container, rid) == "cancelled" and container.runs.cancel(rid) is False

    llm.delay, llm.replies = 0, [act("rename_file", path="root.txt", new_name="c.txt")]

    async def go2():
        live = await container.runs.start("t", rt)
        async for ev in live.bus.subscribe():
            if ev["event"] == "approval_required":
                container.runs.cancel(live.run_id)
                aid = ev["data"]["action_id"]
        return live.run_id, aid

    rid, aid = asyncio.run(go2())
    assert status_of(container, rid) == "cancelled" and container.approvals.get(aid)["status"] == "expired"


def test_runtime_names_and_validation(container):
    for kwargs, code in (
        ({"runtime": "magic"}, "BAD_RUNTIME"),
        ({"max_steps": 0}, "BAD_MAX_STEPS"),
        ({"max_steps": 999}, "BAD_MAX_STEPS"),
    ):
        with pytest.raises(Exception) as e:
            run_agent(container, "t", **kwargs)
        assert e.value.code == code
    with pytest.raises(Exception) as e:
        run_agent(container, "   ")
    assert e.value.code == "EMPTY_TASK"


def test_recover_marks_interrupted_react_runs(container, llm):
    with connect(container.settings.db_path) as con:
        con.execute(
            "INSERT INTO runs(id,task,status,runtime,started_at) VALUES('run_old','x','waiting_approval','react','2026-01-01')"
        )
        con.execute(
            "INSERT INTO runs(id,task,status,runtime,started_at) VALUES('run_lg','x','waiting_approval','langgraph','2026-01-01')"
        )
    assert container.runs.recover() == 1
    assert status_of(container, "run_old") == "failed" and status_of(container, "run_lg") == "waiting_approval"
    assert ScriptedLLM().model == "scripted-model"
