import threading
import time

from tests.conftest import act, final, parse_sse_events


def test_tools_endpoint(client):
    tools = client.get("/tools").json()["tools"]
    assert [t["name"] for t in tools] == [
        "list_files",
        "read_file",
        "search_documents",
        "classify_document",
        "summarize_text",
        "find_duplicates",
        "write_report",
        "move_file",
        "rename_file",
    ]
    mv = [t for t in tools if t["name"] == "move_file"][0]
    assert (
        mv["risk"] == "write"
        and mv["kind"] == "move"
        and mv["requires_approval"] is True
        and "moves" in mv["input_schema"]["properties"]
    )
    assert [t for t in tools if t["name"] == "read_file"][0]["requires_approval"] is False


def test_run_streams_sse_events_for_a_read_only_task(client, llm):
    llm.replies = [act("list_files", path="invoices"), final("Two invoices.")]
    r = client.post("/agent/run", json={"task": "list invoices", "runtime": "react"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    ev = parse_sse_events(r.text)
    assert [k for k, _ in ev] == ["run_started", "thought", "action", "observation", "final"]
    rid = ev[0][1]["run_id"]
    run = client.get(f"/agent/runs/{rid}").json()
    assert run["status"] == "completed" and len(run["steps"]) == 4 and run["steps"][1]["tool_name"] == "list_files"
    assert client.get("/agent/runs").json()["runs"][0]["id"] == rid
    assert client.get("/agent/runs", params={"status": "failed"}).json()["runs"] == []
    replay = parse_sse_events(client.get(f"/agent/runs/{rid}/events").text)
    assert [k for k, _ in replay] == [k for k, _ in ev]  # reconnecting replays history


def test_run_validation(client):
    bad = [
        ({"task": ""}, 422),
        ({"task": "x", "runtime": "magic"}, 422),
        ({"task": "x", "max_steps": 0}, 422),
        ({"task": "x", "max_steps": 99}, 422),
        ({"task": "x", "scope": {"files": ["nope.txt"]}}, 422),
        ({"task": "x", "scope": {"folders": ["../.."]}}, 400),
    ]
    for body, status in bad:
        r = client.post("/agent/run", json=body)
        assert r.status_code == status and "error" in r.json(), body


def test_llm_down_gives_error_event(client, llm):
    from app.errors import AppError

    async def boom(*a, **k):
        raise AppError("LLM_UNAVAILABLE", "Cannot reach Ollama. Run `ollama pull x`", 503)

    llm.chat = boom
    ev = parse_sse_events(client.post("/agent/run", json={"task": "t"}).text)
    assert ev[-1][0] == "error" and ev[-1][1]["code"] == "LLM_UNAVAILABLE" and "ollama pull" in ev[-1][1]["message"]


def test_approve_over_http_while_the_run_is_paused(client, llm, docs):
    llm.replies = [act("write_report", title="API report", content="hello"), final("written")]
    box: dict = {}
    t = threading.Thread(target=lambda: box.setdefault("text", client.post("/agent/run", json={"task": "report"}).text))
    t.start()
    pending = None
    for _ in range(100):
        waiting = client.get("/agent/runs", params={"status": "waiting_approval"}).json()["runs"]
        if waiting:
            pending = client.get(f"/agent/runs/{waiting[0]['id']}").json()["pending_actions"]
            if pending:
                break
        time.sleep(0.05)
    assert (
        pending
        and pending[0]["tool_name"] == "write_report"
        and pending[0]["preview"]["destination"] == "_reports/api-report.md"
    )
    aid = pending[0]["id"]
    assert client.get(f"/agent/actions/{aid}").json()["status"] == "pending"
    assert not (docs / "_reports").exists()
    r = client.post(f"/agent/approve/{aid}", json={"decision": "approve"})
    assert r.json() == {"status": "approved", "resumed_from_checkpoint": False, "run_id": waiting[0]["id"]}
    t.join(timeout=15)
    assert not t.is_alive() and (docs / "_reports" / "api-report.md").exists()
    ev = parse_sse_events(box["text"])
    assert [k for k, _ in ev][-3:] == ["approval_resolved", "observation", "final"]
    assert (
        client.post(f"/agent/approve/{aid}", json={"decision": "approve"}).json()["error"]["code"] == "ALREADY_DECIDED"
    )


def test_approve_validation(client):
    assert client.post("/agent/approve/act_nope", json={"decision": "approve"}).status_code == 404
    assert client.post("/agent/approve/act_nope", json={"decision": "maybe"}).status_code in (404, 422)
    assert client.post("/agent/approve/x", json={}).status_code == 422
    assert client.get("/agent/actions/act_nope").status_code == 404


def test_reject_over_http_and_bad_edit(client, llm, docs):
    llm.replies = [act("rename_file", path="root.txt", new_name="b.txt"), final("fine")]
    t = threading.Thread(target=lambda: client.post("/agent/run", json={"task": "x", "runtime": "langgraph"}))
    t.start()
    aid = None
    for _ in range(100):
        w = client.get("/agent/runs", params={"status": "waiting_approval"}).json()["runs"]
        if w and client.get(f"/agent/runs/{w[0]['id']}").json()["pending_actions"]:
            aid = client.get(f"/agent/runs/{w[0]['id']}").json()["pending_actions"][0]["id"]
            break
        time.sleep(0.05)
    assert aid
    bad = client.post(
        f"/agent/approve/{aid}",
        json={"decision": "approve", "edited_args": {"path": "root.txt", "new_name": "../x.txt"}},
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "BAD_EDITED_ARGS"
    assert (
        client.post(f"/agent/approve/{aid}", json={"decision": "reject", "reason": "no"}).json()["status"] == "rejected"
    )
    t.join(timeout=15)
    assert (docs / "root.txt").exists()


def test_cancel_endpoint(client, llm):
    assert client.post("/agent/runs/run_nope/cancel").status_code == 404
    llm.delay = 5
    t = threading.Thread(target=lambda: client.post("/agent/run", json={"task": "slow"}))
    t.start()
    rid = None
    for _ in range(100):
        runs = client.get("/agent/runs", params={"status": "running"}).json()["runs"]
        if runs:
            rid = runs[0]["id"]
            break
        time.sleep(0.05)
    time.sleep(0.1)
    assert client.post(f"/agent/runs/{rid}/cancel").json() == {"cancelled": True}
    t.join(timeout=10)
    assert client.get(f"/agent/runs/{rid}").json()["status"] == "cancelled"
    assert (
        client.get("/agent/runs/run_nope").status_code == 404
        and client.get("/agent/runs/run_nope/events").status_code == 404
    )
