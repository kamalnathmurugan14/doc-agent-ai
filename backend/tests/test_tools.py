import asyncio

import httpx
import pytest

from app.adapters.classifier import FakeClassifier, HttpClassifier, RuleClassifier, build_classifier
from app.adapters.retriever import Bm25Retriever, FakeRetriever, HttpRetriever, SearchHit, build_retriever
from app.errors import AppError
from app.tools.base import ToolContext, ToolError, compact
from app.tools.read_tools import extractive_summary
from app.tools.registry import Registry
from tests.conftest import ScriptedLLM

REG = Registry()


@pytest.fixture
def ctx(settings):
    return ToolContext(settings, Bm25Retriever(settings), RuleClassifier(), ScriptedLLM(["A short summary."]))


def call(name, ctx, **args):
    t = REG.get(name)
    return asyncio.run(t.run(t.input_model.model_validate(args), ctx))


def preview(name, ctx, **args):
    t = REG.get(name)
    return asyncio.run(t.preview(t.input_model.model_validate(args), ctx))


def test_registry_is_an_allow_list_without_delete():
    names = REG.names()
    assert len(names) == 9 and not any(
        w in n for n in names for w in ("delete", "remove", "rm", "unlink", "shell", "exec")
    )
    assert {n for n, t in REG.tools.items() if t.risk == "write"} == {"write_report", "move_file", "rename_file"}
    assert REG.get("delete_file") is None
    spec = REG.get("move_file").spec(
        REG.get("move_file") and __import__("app.config", fromlist=["Settings"]).Settings(_env_file=None)
    )
    assert spec["requires_approval"] is True and spec["input_schema"]["properties"]["moves"]


def test_list_files(ctx):
    r = call("list_files", ctx)
    paths = [f["path"] for f in r["files"]]
    assert "invoices/jan.txt" in paths and "root.txt" in paths and r["count"] == len(paths)
    assert [f["path"] for f in call("list_files", ctx, path="invoices", pattern="feb")["files"]] == ["invoices/feb.txt"]
    assert all("/" not in f["path"] for f in call("list_files", ctx, recursive=False)["files"])
    assert call("list_files", ctx, max_items=2)["truncated"] is True
    with pytest.raises(ToolError):
        call("list_files", ctx, path="nope")
    with pytest.raises(ToolError, match="not allowed"):
        call("list_files", ctx, path="../..")


def test_read_file_paging_and_safety(ctx, docs):
    (docs / "long.txt").write_text("INVOICE " + "0123456789 " * 60, encoding="utf-8")
    r = call("read_file", ctx, path="long.txt", max_chars=100)
    assert r["text"].startswith("INVOICE") and r["truncated"] is True and r["total_chars"] > 100
    r2 = call("read_file", ctx, path="long.txt", start=100, max_chars=100)
    assert r2["start"] == 100 and r2["text"] != r["text"]
    for bad in ("../../etc/passwd", "/etc/passwd", "C:/Windows/win.ini"):
        with pytest.raises(ToolError, match="not allowed"):
            call("read_file", ctx, path=bad)
    (docs / "x.exe").write_bytes(b"MZ")
    with pytest.raises(ToolError, match="Unsupported"):
        call("read_file", ctx, path="x.exe")
    with pytest.raises(ToolError, match="not found"):
        call("read_file", ctx, path="missing.txt")


def test_symlink_escape_is_blocked(ctx, docs, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    (docs / "link.txt").symlink_to(secret)
    with pytest.raises(ToolError, match="not allowed"):
        call("read_file", ctx, path="link.txt")
    assert "link.txt" not in [f["path"] for f in call("list_files", ctx)["files"]]  # skipped, and listing still works
    assert (
        call("search_documents", ctx, query="secret")["count"] == 0
    )  # the outside file is never indexed by the fallback search


def test_scope_restricts_everything(settings):
    c = ToolContext(
        settings, Bm25Retriever(settings), RuleClassifier(), ScriptedLLM(), scope_folders=["invoices"], scope_files=None
    )
    assert {f["path"].split("/")[0] for f in call("list_files", c)["files"]} == {"invoices"}
    with pytest.raises(ToolError, match="outside the scope"):
        call("read_file", c, path="notes/ideas.txt")
    assert all(h["path"].startswith("invoices/") for h in call("search_documents", c, query="invoice total")["results"])
    c2 = ToolContext(settings, Bm25Retriever(settings), RuleClassifier(), ScriptedLLM(), scope_files=["root.txt"])
    assert [f["path"] for f in call("list_files", c2)["files"]] == ["root.txt"]


def test_search_documents_bm25_fallback(ctx):
    r = call("search_documents", ctx, query="termination notice agreement")
    assert (
        r["engine"] == "bm25-fallback"
        and r["results"][0]["path"] == "contracts/service.md"
        and "Termination" in r["results"][0]["snippet"]
    )
    assert call("search_documents", ctx, query="zzzzqqqq wwwwxxxx")["results"] == []


def test_bm25_index_refreshes_on_change(ctx, docs):
    assert call("search_documents", ctx, query="pineapple")["count"] == 0
    (docs / "fruit.txt").write_text("I love pineapple pizza", encoding="utf-8")
    assert call("search_documents", ctx, query="pineapple")["results"][0]["path"] == "fruit.txt"


def test_classify_with_rules_and_fake(ctx, settings):
    r = call("classify_document", ctx, path="invoices/jan.txt")
    assert r["category"] == "Invoice" and r["method"] == "keyword-rules" and 0 < r["confidence"] <= 1
    assert call("classify_document", ctx, path="contracts/service.md")["category"] == "Contract"
    assert call("classify_document", ctx, path="notes/ideas.txt")["category"] == "Other"
    c = ToolContext(settings, FakeRetriever(), FakeClassifier("Resume"), ScriptedLLM())
    assert call("classify_document", c, path="root.txt")["category"] == "Resume"


def test_summarize_llm_and_fallback(ctx, settings):
    r = call("summarize_text", ctx, path="contracts/service.md")
    assert r == {"source": "contracts/service.md", "summary": "A short summary.", "method": "llm"}
    assert call("summarize_text", ctx, text="Some text to summarize here, long enough.")["source"] is None

    class Broken(ScriptedLLM):
        async def chat(self, *a, **k):
            raise AppError("LLM_UNAVAILABLE", "down", 503)

    c = ToolContext(settings, FakeRetriever(), FakeClassifier(), Broken())
    r = call("summarize_text", c, path="contracts/service.md")
    assert r["method"] == "extractive-fallback" and "agreement" in r["summary"].lower()
    with pytest.raises(ValueError):
        REG.get("summarize_text").input_model.model_validate({})
    with pytest.raises(ValueError):
        REG.get("summarize_text").input_model.model_validate({"path": "a.txt", "text": "b"})


def test_extractive_summary():
    text = (
        "Cats are small animals that purr loudly. " * 3
        + "Quarterly budgets were approved by the board this week. "
        + "Dogs bark at strangers near the gate. "
    )
    s = extractive_summary(text, 2)
    assert 1 <= len(s.split(". ")) <= 3 and extractive_summary("tiny", 2) == "tiny"


def test_find_duplicates(ctx, docs):
    (docs / "invoices" / "jan_edit.txt").write_text(
        (docs / "invoices" / "jan.txt").read_text() + "\nPS: thank you for your business with us today.",
        encoding="utf-8",
    )
    r = call("find_duplicates", ctx, near_threshold=0.5)
    assert ["invoices/jan.txt", "invoices/jan_copy.txt"] in [sorted(g) for g in r["exact_groups"]]
    assert any("invoices/jan_edit.txt" in n["files"] for n in r["near_duplicates"])
    assert not any("notes/ideas.txt" in n["files"] for n in r["near_duplicates"])
    assert call("find_duplicates", ctx, path="notes")["exact_groups"] == []


def test_write_report_never_overwrites(ctx, docs):
    args = {"title": "Q1 Summary!", "content": "## Totals\n- $1,440"}
    p = preview("write_report", ctx, **args)
    assert p["destination"] == "_reports/q1-summary.md" and "Totals" in p["content_head"]
    r1 = call("write_report", ctx, **args)
    r2 = call("write_report", ctx, **args)
    assert r1["written"] == "_reports/q1-summary.md" and r2["written"] == "_reports/q1-summary_1.md"
    assert (docs / "_reports" / "q1-summary.md").read_text().startswith("# Q1 Summary!")
    assert ctx.artifacts == ["_reports/q1-summary.md", "_reports/q1-summary_1.md"]
    r3 = call("write_report", ctx, title="x", content="y", filename="../../evil.md")
    assert r3["written"].startswith("_reports/") and ".." not in r3["written"]


def test_move_file_batch_validation(ctx, docs):
    moves = [
        {"source": "invoices/jan.txt", "destination": "Invoices/"},  # folder, keeps name
        {"source": "invoices/feb.txt", "destination": "invoices/jan_copy.txt"},  # overwrite -> refused
        {"source": "notes/ideas.txt", "destination": "notes/ideas.pdf"},  # extension change -> refused
        {"source": "root.txt", "destination": "../../outside.txt"},  # escape -> refused
        {"source": "missing.txt", "destination": "x/"},  # missing
        {
            "source": "contracts/service.md",
            "destination": "Invoices/jan.txt",
        },  # same destination as item 0? (jan.txt) different ext -> refused
    ]
    p = preview("move_file", ctx, moves=moves)
    ok = [i["ok"] for i in p["items"]]
    assert ok == [True, False, False, False, False, False] and p["ok_count"] == 1
    assert (
        "already exists" in p["items"][1]["problem"]
        and "extension" in p["items"][2]["problem"]
        and "not allowed" in p["items"][3]["problem"]
    )
    r = call("move_file", ctx, moves=moves)
    assert r["moved"] == 1 and (docs / "Invoices" / "jan.txt").exists() and not (docs / "invoices" / "jan.txt").exists()
    assert (docs / "invoices" / "feb.txt").exists() and (
        docs / "notes" / "ideas.txt"
    ).exists()  # refused moves changed nothing
    assert not (docs.parent / "outside.txt").exists()


def test_move_same_destination_in_batch(ctx):
    p = preview(
        "move_file",
        ctx,
        moves=[
            {"source": "invoices/jan.txt", "destination": "x/a.txt"},
            {"source": "invoices/feb.txt", "destination": "x/a.txt"},
        ],
    )
    assert [i["ok"] for i in p["items"]] == [True, False] and "same destination" in p["items"][1]["problem"]


def test_rename_file(ctx, docs):
    assert preview("rename_file", ctx, path="root.txt", new_name="budget.txt") == {
        "action": "rename_file",
        "before": "root.txt",
        "after": "budget.txt",
    }
    assert call("rename_file", ctx, path="root.txt", new_name="budget.txt")["renamed"] == {
        "from": "root.txt",
        "to": "budget.txt",
    }
    assert (docs / "budget.txt").exists() and not (docs / "root.txt").exists()
    with pytest.raises(ToolError, match="already exists"):
        call("rename_file", ctx, path="invoices/feb.txt", new_name="jan.txt")
    with pytest.raises(ToolError, match="extension"):
        call("rename_file", ctx, path="invoices/feb.txt", new_name="feb.pdf")
    for bad in ("../x.txt", "a/b.txt", "..", "a\\b.txt"):
        with pytest.raises(ValueError):
            REG.get("rename_file").input_model.model_validate({"path": "root.txt", "new_name": bad})


def test_compact_truncates_big_outputs():
    big = {"text": "x" * 5000}
    out = compact(big, 1000)
    assert out["truncated"] is True and len(out["partial_json"]) == 1000
    assert compact({"a": 1}, 1000) == {"a": 1}


def test_http_adapters_with_mock_transport(monkeypatch):
    import app.adapters.classifier as cm
    import app.adapters.retriever as rm

    real = httpx.AsyncClient

    def handler(req: httpx.Request):
        if req.url.path == "/retrieve":
            return httpx.Response(
                200, json={"hits": [{"rel_path": "a.txt", "page": 2, "similarity": 0.8, "text": "hello   world"}]}
            )
        if req.url.path == "/predict":
            return httpx.Response(
                200, json={"predictions": [{"category": "Invoice", "confidence": 0.9}], "uncertain": False}
            )
        return httpx.Response(200, json={"status": "ok"})

    for mod in (cm, rm):
        monkeypatch.setattr(mod.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    hits = asyncio.run(HttpRetriever("http://rag:8004").search("hello", 3, ["a.txt"]))
    assert hits == [SearchHit("a.txt", 2, 0.8, "hello world")]
    c = asyncio.run(HttpClassifier("http://clf:8002").classify("", "a.txt"))
    assert c["category"] == "Invoice" and c["method"] == "classifier-service"
    assert asyncio.run(HttpRetriever("http://rag:8004").ping()) is True


def test_http_adapters_report_unreachable(monkeypatch):
    import app.adapters.classifier as cm
    import app.adapters.retriever as rm

    def boom(req):
        raise httpx.ConnectError("refused")

    real = httpx.AsyncClient
    for mod in (cm, rm):
        monkeypatch.setattr(mod.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(boom), **kw))
    with pytest.raises(AppError) as e:
        asyncio.run(HttpRetriever("http://rag:8004").search("x", 3, None))
    assert e.value.code == "RAG_UNAVAILABLE"
    with pytest.raises(AppError) as e:
        asyncio.run(HttpClassifier("http://clf:8002").classify("", "a.txt"))
    assert e.value.code == "CLASSIFIER_UNAVAILABLE"
    assert asyncio.run(HttpClassifier("http://clf").ping()) is False


def test_adapter_selection_from_settings(settings):
    assert build_retriever(settings).name == "bm25-fallback" and build_classifier(settings).name == "keyword-rules"
    settings.rag_service_url, settings.classifier_service_url = "http://localhost:8004", "http://localhost:8002"
    assert build_retriever(settings).name == "rag-service" and build_classifier(settings).name == "classifier-service"


def test_tool_error_inside_search_adapter(settings):
    class Broken(FakeRetriever):
        async def search(self, *a, **k):
            raise AppError("RAG_UNAVAILABLE", "down", 503)

    c = ToolContext(settings, Broken(), FakeClassifier(), ScriptedLLM())
    with pytest.raises(AppError):
        call("search_documents", c, query="anything")
