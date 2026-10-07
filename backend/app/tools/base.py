"""Tool contract: name, LLM-facing description, Pydantic input schema, risk label, run(), and preview() for write tools."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel

from app.adapters.classifier import Classifier
from app.adapters.llm import ChatLLM
from app.adapters.retriever import Retriever
from app.config import Settings
from app.core.paths import ext_of, rel_posix, safe_resolve
from app.errors import AppError


class ToolError(Exception):
    """A problem the agent can recover from; the message is returned to the model as the observation."""


@dataclass
class ToolContext:
    settings: Settings
    retriever: Retriever
    classifier: Classifier
    llm: ChatLLM
    scope_files: list[str] | None = None  # None = whole DOCS_ROOT
    scope_folders: list[str] = field(default_factory=list)
    dry_run: bool = False
    artifacts: list[str] = field(default_factory=list)

    @property
    def root(self) -> Path:
        return self.settings.docs_root.resolve()

    def resolve(self, rel: str) -> Path:
        """Every path an agent supplies goes through here: must stay inside DOCS_ROOT."""
        try:
            return safe_resolve(self.settings.docs_root, rel)
        except AppError as exc:
            raise ToolError(f"Path '{rel}' is not allowed: {exc.message}") from exc

    def rel(self, p: Path) -> str:
        return rel_posix(self.settings.docs_root, p)

    def in_scope(self, rel: str) -> bool:
        if self.scope_files is None and not self.scope_folders:
            return True
        if self.scope_files and rel in self.scope_files:
            return True
        return any(rel == f or rel.startswith(f.rstrip("/") + "/") for f in self.scope_folders)

    def require_scope(self, rel: str) -> None:
        if not self.in_scope(rel):
            raise ToolError(f"'{rel}' is outside the scope selected for this task")

    def allowed_file(self, rel: str) -> Path:
        p = self.resolve(rel)
        if not p.is_file():
            raise ToolError(f"File not found: {rel}")
        if ext_of(p.name) not in self.settings.extensions:
            raise ToolError(f"Unsupported file type: {rel}")
        self.require_scope(self.rel(p))
        return p

    def list_docs(self, base: str = "", recursive: bool = True) -> list[Path]:
        root = self.resolve(base)
        if not root.is_dir():
            raise ToolError(f"Folder not found: {base or '.'}")
        it = root.rglob("*") if recursive else root.iterdir()
        out = []
        for p in sorted(it):
            try:
                parts = (
                    p.resolve().relative_to(self.root).parts
                )  # a symlink pointing outside DOCS_ROOT is skipped, never followed
            except ValueError:
                continue
            if (
                p.is_file()
                and not any(x.startswith(".") for x in parts)
                and ext_of(p.name) in self.settings.extensions
                and self.in_scope(self.rel(p))
            ):
                out.append(p)
        return out


class Tool:
    name: ClassVar[str]
    description: ClassVar[str]
    input_model: ClassVar[type[BaseModel]]
    risk: ClassVar[str] = "read"  # read | write
    kind: ClassVar[str] = "read"  # read | write | move | rename  (matched against REQUIRE_APPROVAL)

    async def run(self, args: Any, ctx: ToolContext) -> dict:
        raise NotImplementedError

    async def preview(self, args: Any, ctx: ToolContext) -> dict:
        raise NotImplementedError(f"{self.name} has no preview")

    def spec(self, settings: Settings) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
            "risk": self.risk,
            "kind": self.kind,
            "requires_approval": self.risk == "write" and self.kind in settings.approval_kinds,
        }


def compact(result: Any, limit: int) -> Any:
    """Keep observations small: oversized results are cut with an explicit 'truncated' marker."""
    s = json.dumps(result, ensure_ascii=False, default=str)
    if len(s) <= limit:
        return result
    return {
        "truncated": True,
        "note": f"output was {len(s)} characters; showing the first {limit}",
        "partial_json": s[:limit],
    }
