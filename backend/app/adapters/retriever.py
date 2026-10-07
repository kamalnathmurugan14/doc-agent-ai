"""Retriever adapter: HTTP client to project 4 (RAG), a built-in BM25 fallback, and a fake for tests."""

import re
from dataclasses import dataclass
from typing import Protocol

import httpx
from rank_bm25 import BM25Okapi

from app.config import Settings
from app.core.extractors import extract
from app.core.paths import ext_of, rel_posix
from app.errors import AppError

_TOK = re.compile(r"[a-z0-9]+")


@dataclass
class SearchHit:
    path: str
    page: int
    score: float
    snippet: str

    def as_dict(self) -> dict:
        return {"path": self.path, "page": self.page, "score": round(self.score, 4), "snippet": self.snippet}


class Retriever(Protocol):
    name: str

    async def search(self, query: str, top_k: int, files: list[str] | None) -> list[SearchHit]: ...
    async def ping(self) -> bool: ...


def _inside(root, p) -> bool:
    """False for symlinks that point outside DOCS_ROOT (they must never be read)."""
    try:
        p.resolve().relative_to(root)
        return True
    except ValueError:
        return False


def snippet(text: str, query: str, width: int = 240) -> str:
    low, words = text.lower(), [w for w in _TOK.findall(query.lower()) if len(w) > 2]
    pos = min((low.find(w) for w in words if w in low), default=0)
    start = max(0, pos - 60)
    return " ".join(text[start : start + width].split())


class Bm25Retriever:
    """Built-in fallback: BM25 over page-level text of the files in DOCS_ROOT (rebuilt when files change)."""

    name = "bm25-fallback"

    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self._sig: tuple | None = None
        self._pages: list[tuple[str, int, str]] = []
        self._bm25: BM25Okapi | None = None

    def _build(self) -> None:
        root = self.s.docs_root.resolve()
        files = [
            p
            for p in sorted(root.rglob("*"))
            if p.is_file()
            and ext_of(p.name) in self.s.extensions
            and _inside(root, p)
            and not any(x.startswith(".") for x in p.relative_to(root).parts)
        ]
        sig = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in files)
        if sig == self._sig:
            return
        pages: list[tuple[str, int, str]] = []
        for p in files:
            try:
                pages += [(rel_posix(root, p), n, t) for n, t in extract(p).pages]
            except Exception:  # noqa: BLE001 - unreadable files are simply not searchable
                continue
        self._pages, self._sig = pages, sig
        self._bm25 = BM25Okapi([_TOK.findall(t.lower()) or ["_"] for _, _, t in pages]) if pages else None

    async def search(self, query: str, top_k: int, files: list[str] | None) -> list[SearchHit]:
        self._build()
        q = _TOK.findall(query.lower())
        if not self._bm25 or not q:
            return []
        scores = self._bm25.get_scores(q)
        order = sorted(range(len(scores)), key=lambda i: -scores[i])
        out: list[SearchHit] = []
        for i in order:
            path, page, text = self._pages[i]
            if files is not None and path not in files:
                continue
            if not set(q) & set(_TOK.findall(text.lower())):
                continue  # BM25 can score unrelated pages > 0 on tiny corpora; require a real term match
            out.append(SearchHit(path, page, float(scores[i]), snippet(text, query)))
            if len(out) >= top_k:
                break
        return out

    async def ping(self) -> bool:
        return True


class HttpRetriever:
    """Calls project 4 (rag-doc-chatbot) `POST /retrieve`. Both projects must point at the same DOCS_ROOT."""

    name = "rag-service"

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base, self.timeout = base_url.rstrip("/"), timeout

    async def search(self, query: str, top_k: int, files: list[str] | None) -> list[SearchHit]:
        body = {"query": query, "options": {"top_k": top_k}, "scope": {"files": files or []}}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as http:
                r = await http.post(f"{self.base}/retrieve", json=body)
        except httpx.HTTPError as exc:
            raise AppError("RAG_UNAVAILABLE", f"RAG service at {self.base} is not reachable", 503) from exc
        if r.status_code >= 400:
            raise AppError("RAG_ERROR", f"RAG service returned HTTP {r.status_code}", 502)
        return [
            SearchHit(
                h["rel_path"],
                int(h.get("page", 1)),
                float(h.get("similarity", 0)),
                " ".join(str(h.get("text", "")).split())[:240],
            )
            for h in r.json().get("hits", [])
        ]

    async def ping(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as http:
                return (await http.get(f"{self.base}/health")).status_code == 200
        except httpx.HTTPError:
            return False


class FakeRetriever:
    name = "fake"

    def __init__(self, hits: list[SearchHit] | None = None) -> None:
        self.hits, self.calls = hits or [], []

    async def search(self, query: str, top_k: int, files: list[str] | None) -> list[SearchHit]:
        self.calls.append((query, top_k, files))
        return [h for h in self.hits if files is None or h.path in files][:top_k]

    async def ping(self) -> bool:
        return True


def build_retriever(settings: Settings) -> Retriever:
    return HttpRetriever(settings.rag_service_url) if settings.rag_service_url else Bm25Retriever(settings)
