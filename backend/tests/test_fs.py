import os

import pytest

from app.core.paths import safe_resolve, sanitize_filename
from app.errors import AppError


@pytest.mark.parametrize("bad", ["../../etc/passwd", "/etc/passwd", "C:/Windows", "..\\..\\x", "sub/../../x", "a\x00b"])
def test_safe_resolve_rejects(docs, bad):
    with pytest.raises(AppError) as e:
        safe_resolve(docs, bad)
    assert e.value.code == "PATH_FORBIDDEN"


def test_safe_resolve_ok(docs):
    assert safe_resolve(docs, "notes/ideas.txt").name == "ideas.txt"
    assert safe_resolve(docs, "") == docs.resolve()


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_symlink_escape_rejected(docs, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (docs / "link").symlink_to(outside)
    with pytest.raises(AppError):
        safe_resolve(docs, "link")


def test_sanitize_filename():
    assert sanitize_filename("../../evil.txt") == "evil.txt"
    assert sanitize_filename("a b<>c.pdf") == "a b__c.pdf"
    with pytest.raises(AppError):
        sanitize_filename("...")


def test_tree_root_and_sub(client):
    r = client.get("/fs/tree").json()
    names = {e["name"] for e in r["entries"]}
    assert {"invoices", "contracts", "root.txt"} <= names
    assert r["entries"][0]["type"] == "dir"  # folders first
    assert client.get("/fs/tree", params={"path": "notes"}).json()["entries"][0]["name"] == "ideas.txt"


def test_tree_traversal_and_missing(client):
    r = client.get("/fs/tree", params={"path": "../.."})
    assert r.status_code == 400 and r.json()["error"]["code"] == "PATH_FORBIDDEN"
    assert client.get("/fs/tree", params={"path": "nope"}).status_code == 404
    assert client.get("/fs/tree", params={"path": "root.txt"}).status_code == 400


def test_upload_ok_and_no_overwrite(client, docs):
    f = {"files": ("new note.txt", b"hello", "text/plain")}
    assert client.post("/fs/upload", files=f).json()["saved"] == ["new note.txt"]
    assert client.post("/fs/upload", files=f).json()["saved"] == ["new note_1.txt"]
    assert (docs / "new note.txt").read_bytes() == b"hello"


def test_upload_into_subfolder_and_traversal(client, docs):
    f = {"files": ("a.md", b"x", "text/markdown")}
    assert client.post("/fs/upload", params={"path": "notes"}, files=f).json()["saved"] == ["notes/a.md"]
    assert client.post("/fs/upload", params={"path": "../.."}, files=f).status_code == 400


def test_upload_filename_sanitised(client, docs):
    f = {"files": ("../../evil.txt", b"x", "text/plain")}
    assert client.post("/fs/upload", files=f).json()["saved"] == ["evil.txt"]


def test_upload_bad_extension_and_oversize(client):
    r = client.post("/fs/upload", files={"files": ("x.exe", b"x", "application/octet-stream")})
    assert r.status_code == 415 and r.json()["error"]["code"] == "BAD_EXTENSION"
    r = client.post("/fs/upload", files={"files": ("big.txt", b"a" * (1024 * 1024 + 5), "text/plain")})
    assert r.status_code == 413 and r.json()["error"]["code"] == "TOO_LARGE"


def test_health_and_error_shape(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["ollama"] is True and h["retriever"] == {"name": "bm25-fallback", "ok": True}
    assert h["classifier"]["name"] == "fake" and h["require_approval"] == ["move", "rename", "write"]
    r = client.post("/agent/run", json={})
    assert r.status_code == 422 and "error" in r.json()


def test_download(client, docs):
    r = client.get("/fs/download", params={"path": "notes/ideas.txt"})
    assert r.status_code == 200 and "Brainstorm" in r.text and "ideas.txt" in r.headers["content-disposition"]
    assert client.get("/fs/download", params={"path": "../../etc/passwd"}).status_code == 400
    assert client.get("/fs/download", params={"path": "nope.txt"}).status_code == 404
    (docs / "run.sh").write_text("echo hi")
    assert client.get("/fs/download", params={"path": "run.sh"}).status_code == 404  # not an allowed document type
