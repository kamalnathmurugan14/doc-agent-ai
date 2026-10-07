"""Write tools. They never delete and never overwrite; each has a preview() that is shown before the user approves."""

import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from app.core.paths import ext_of
from app.tools.base import Tool, ToolContext, ToolError

_SLUG = re.compile(r"[^a-z0-9]+")


def unique_path(p: Path) -> Path:
    """Never overwrite: report.md -> report_1.md -> report_2.md ..."""
    n, q = 1, p
    while q.exists():
        q = p.with_name(f"{p.stem}_{n}{p.suffix}")
        n += 1
    return q


class WriteReportIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=60000, description="Markdown body of the report")
    filename: str | None = Field(default=None, max_length=80, description="Optional file name (without folders)")


class WriteReport(Tool):
    name = "write_report"
    description = (
        "Write a Markdown report into the reports folder. Requires user approval. Never overwrites existing files."
    )
    input_model = WriteReportIn
    risk = "write"
    kind = "write"

    def _target(self, args: WriteReportIn, ctx: ToolContext) -> Path:
        base = _SLUG.sub("-", (args.filename or args.title).lower().removesuffix(".md")).strip("-")[:60] or "report"
        folder = ctx.resolve(ctx.settings.reports_dir)
        return unique_path(folder / f"{base}.md")

    async def preview(self, args: WriteReportIn, ctx: ToolContext) -> dict:
        t = self._target(args, ctx)
        return {
            "action": "create_file",
            "destination": ctx.rel(t),
            "bytes": len(args.content.encode()),
            "content_head": args.content[:1200],
            "note": "A new file will be created; existing files are never overwritten.",
        }

    async def run(self, args: WriteReportIn, ctx: ToolContext) -> dict:
        t = self._target(args, ctx)
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(f"# {args.title}\n\n{args.content}\n", encoding="utf-8")
        ctx.artifacts.append(ctx.rel(t))
        return {"written": ctx.rel(t), "bytes": t.stat().st_size}


class Move(BaseModel):
    source: str
    destination: str = Field(description="New path (or an existing folder / path ending in '/' to keep the file name)")


class MoveFileIn(BaseModel):
    moves: list[Move] = Field(
        min_length=1, max_length=50, description="One or more moves, proposed together as a single batch"
    )


def plan_move(m: Move, ctx: ToolContext, taken: set[str]) -> tuple[Path | None, Path | None, str | None]:
    """Validate one move. Returns (src, dst, problem)."""
    try:
        src = ctx.allowed_file(m.source)
        dst = ctx.resolve(m.destination)
    except ToolError as exc:
        return None, None, str(exc)
    if m.destination.endswith("/") or dst.is_dir():
        dst = dst / src.name
    if ext_of(dst.name) != ext_of(src.name):
        return src, dst, "the file extension must not change"
    if dst == src:
        return src, dst, "source and destination are the same"
    if dst.exists():
        return src, dst, "destination already exists (files are never overwritten)"
    if str(dst) in taken:
        return src, dst, "another move in this batch has the same destination"
    return src, dst, None


class MoveFile(Tool):
    name = "move_file"
    description = (
        "Move one or more files to new locations (batch). Requires user approval, who can untick individual moves. "
        "Never overwrites; creates destination folders as needed."
    )
    input_model = MoveFileIn
    risk = "write"
    kind = "move"

    async def preview(self, args: MoveFileIn, ctx: ToolContext) -> dict:
        taken: set[str] = set()
        items = []
        for i, m in enumerate(args.moves):
            src, dst, problem = plan_move(m, ctx, taken)
            if dst and not problem:
                taken.add(str(dst))
            items.append(
                {
                    "index": i,
                    "source": ctx.rel(src) if src else m.source,
                    "destination": ctx.rel(dst) if dst else m.destination,
                    "ok": problem is None,
                    "problem": problem,
                }
            )
        return {
            "action": "move_files",
            "items": items,
            "ok_count": sum(1 for x in items if x["ok"]),
            "after": sorted({x["destination"] for x in items if x["ok"]}),
        }

    async def run(self, args: MoveFileIn, ctx: ToolContext) -> dict:
        taken: set[str] = set()
        results = []
        for m in args.moves:
            src, dst, problem = plan_move(m, ctx, taken)
            if problem or src is None or dst is None:
                results.append({"source": m.source, "status": "skipped", "reason": problem})
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)  # os.rename never replaces silently on Windows; we also pre-checked existence
            taken.add(str(dst))
            ctx.artifacts.append(ctx.rel(dst))
            results.append({"source": ctx.rel(src), "destination": ctx.rel(dst), "status": "moved"})
        return {"moved": sum(r["status"] == "moved" for r in results), "results": results}


class RenameFileIn(BaseModel):
    path: str
    new_name: str = Field(
        min_length=1, max_length=150, description="New file name only (no folders). Keep the extension."
    )

    @field_validator("new_name")
    @classmethod
    def _plain_name(cls, v: str) -> str:
        if "/" in v or "\\" in v or v in (".", "..") or "\x00" in v:
            raise ValueError("new_name must be a plain file name without folders")
        return v


class RenameFile(Tool):
    name = "rename_file"
    description = "Rename a file in place (same folder, same extension). Requires user approval. Never overwrites."
    input_model = RenameFileIn
    risk = "write"
    kind = "rename"

    def _plan(self, args: RenameFileIn, ctx: ToolContext) -> tuple[Path, Path]:
        src = ctx.allowed_file(args.path)
        dst = src.with_name(args.new_name)
        if ext_of(dst.name) != ext_of(src.name):
            raise ToolError("the file extension must not change")
        if dst.exists():
            raise ToolError(f"'{args.new_name}' already exists in that folder (files are never overwritten)")
        return src, dst

    async def preview(self, args: RenameFileIn, ctx: ToolContext) -> dict:
        src, dst = self._plan(args, ctx)
        return {"action": "rename_file", "before": ctx.rel(src), "after": ctx.rel(dst)}

    async def run(self, args: RenameFileIn, ctx: ToolContext) -> dict:
        src, dst = self._plan(args, ctx)
        src.rename(dst)
        ctx.artifacts.append(ctx.rel(dst))
        return {"renamed": {"from": ctx.rel(src), "to": ctx.rel(dst)}}
