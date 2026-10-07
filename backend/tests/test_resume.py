import subprocess
import sys
import time
from pathlib import Path

from app.adapters.classifier import FakeClassifier
from app.adapters.retriever import Bm25Retriever
from app.deps import Container
from tests.conftest import ScriptedLLM, final


def crash_during_approval(settings, runtime_marker="langgraph") -> tuple[str, str]:
    out = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parent / "crash_helper.py"),
            str(settings.docs_root),
            str(settings.data_dir),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    line = [ln for ln in out.stdout.splitlines() if ln.startswith("READY")]
    assert line, out.stderr[-2000:]
    _, action_id, run_id = line[0].split()
    return action_id, run_id


def wait_status(container, run_id, want, timeout=15):
    for _ in range(int(timeout / 0.1)):
        s = container.runs.get_row(run_id)["status"]
        if s in want:
            return s
        time.sleep(0.1)
    raise AssertionError(f"run stayed {s}")


def test_langgraph_run_resumes_from_sqlite_checkpoint_after_a_crash(settings, docs, tmp_path):
    action_id, run_id = crash_during_approval(settings)
    assert (docs / "root.txt").exists()  # nothing happened before approval

    # a brand-new process (new Container, new graph object) with the same data directory
    from fastapi.testclient import TestClient

    from app.main import create_app

    llm = ScriptedLLM([final("Renamed after the restart.")])
    container = Container(settings, llm=llm, retriever=Bm25Retriever(settings), classifier=FakeClassifier())
    assert container.runs.get_row(run_id)["status"] == "waiting_approval"  # recover() leaves LangGraph runs alone
    with TestClient(create_app(settings, container)) as c:
        pend = c.get(f"/agent/runs/{run_id}").json()["pending_actions"]
        assert [p["id"] for p in pend] == [action_id] and pend[0]["preview"]["after"] == "renamed.txt"
        r = c.post(f"/agent/approve/{action_id}", json={"decision": "approve"})
        assert r.status_code == 200 and r.json()["resumed_from_checkpoint"] is True
        assert wait_status(container, run_id, {"completed", "failed"}) == "completed"
        trace = c.get(f"/agent/runs/{run_id}").json()
        assert (
            c.post(f"/agent/approve/{action_id}", json={"decision": "approve"}).status_code == 409
        )  # cannot decide twice
    assert (docs / "renamed.txt").exists() and not (docs / "root.txt").exists()
    assert trace["final_answer"] == "Renamed after the restart."
    types = [s["type"] for s in trace["steps"]]
    assert types == ["thought", "action", "approval", "approval", "observation", "final"] and [
        s["idx"] for s in trace["steps"]
    ] == list(range(6))
    # the resumed process asked the model exactly once (for the final answer) and replayed the tool result to it
    assert len(llm.calls) == 1 and "renamed" in llm.calls[0]["messages"][-1]["content"]


def test_langgraph_reject_after_crash(settings, docs):
    action_id, run_id = crash_during_approval(settings)
    llm = ScriptedLLM([final("Okay, left it.")])
    container = Container(settings, llm=llm, retriever=Bm25Retriever(settings), classifier=FakeClassifier())
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(settings, container)) as c:
        assert (
            c.post(f"/agent/approve/{action_id}", json={"decision": "reject", "reason": "not now"}).json()[
                "resumed_from_checkpoint"
            ]
            is True
        )
        wait_status(container, run_id, {"completed"})
    assert (docs / "root.txt").exists() and "User rejected this action: not now" in llm.calls[0]["messages"][-1][
        "content"
    ]


def test_react_run_cannot_resume_after_a_crash(settings, docs):
    """ReAct keeps its loop in memory: after a restart the run is marked failed and the pending action expires."""
    from app.db.session import connect

    Container(
        settings, llm=ScriptedLLM(), retriever=Bm25Retriever(settings), classifier=FakeClassifier()
    )  # creates the DB
    with connect(settings.db_path) as con:
        con.execute(
            "INSERT INTO runs(id,task,status,runtime,started_at) VALUES('run_x','t','waiting_approval','react','2026-01-01')"
        )
        con.execute(
            "INSERT INTO pending_actions(id,run_id,tool_name,args_json,risk,preview_json,created_at) VALUES('act_x','run_x','rename_file','{}','write','{}','2026-01-01')"
        )
    container2 = Container(
        settings, llm=ScriptedLLM(), retriever=Bm25Retriever(settings), classifier=FakeClassifier()
    )  # "restart"
    assert (
        container2.runs.get_row("run_x")["status"] == "failed"
        and "INTERRUPTED" in container2.runs.get_row("run_x")["error"]
    )
    assert container2.approvals.get("act_x")["status"] == "expired"
