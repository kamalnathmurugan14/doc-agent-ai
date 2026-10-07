"""Safe filesystem endpoints: browse DOCS_ROOT and upload into it."""

import datetime as dt

from fastapi import APIRouter, File, Request, UploadFile

from app.core.paths import ext_of, rel_posix, safe_resolve, sanitize_filename
from app.errors import AppError

router = APIRouter(prefix="/fs")


@router.get("/tree")
def tree(request: Request, path: str = "") -> dict:
    s = request.app.state.container.settings
    target = safe_resolve(s.docs_root, path)
    if not target.exists():
        raise AppError("NOT_FOUND", "Folder not found", 404)
    if not target.is_dir():
        raise AppError("NOT_A_FOLDER", "Path is not a folder", 400)
    entries = []
    for p in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if p.name.startswith("."):
            continue
        try:
            resolved = p.resolve()
            rel_posix(s.docs_root, resolved)  # skip symlinks pointing outside the root
        except ValueError:
            continue
        is_dir = p.is_dir()
        if not is_dir and ext_of(p.name) not in s.extensions:
            continue
        st = p.stat()
        entries.append(
            {
                "name": p.name,
                "type": "dir" if is_dir else "file",
                "size": 0 if is_dir else st.st_size,
                "modified": dt.datetime.fromtimestamp(st.st_mtime, dt.UTC).isoformat(timespec="seconds"),
                "path": rel_posix(s.docs_root, resolved),
            }
        )
    return {"path": "" if target == s.docs_root.resolve() else rel_posix(s.docs_root, target), "entries": entries}


@router.post("/upload")
async def upload(request: Request, files: list[UploadFile] = File(...), path: str = "") -> dict:
    s = request.app.state.container.settings
    dest = safe_resolve(s.docs_root, path)
    dest.mkdir(parents=True, exist_ok=True)
    limit = s.max_upload_mb * 1024 * 1024
    saved = []
    for up in files:
        name = sanitize_filename(up.filename or "")
        if ext_of(name) not in s.extensions:
            raise AppError("BAD_EXTENSION", f"Only {', '.join(sorted(s.extensions))} files are allowed", 415)
        data = await up.read(limit + 1)
        if len(data) > limit:
            raise AppError("TOO_LARGE", f"File exceeds {s.max_upload_mb} MB", 413)
        target = safe_resolve(s.docs_root, (dest / name).relative_to(s.docs_root.resolve()).as_posix())
        n = 1
        while target.exists():  # never overwrite
            target = target.with_name(f"{target.stem}_{n}{target.suffix}")
            n += 1
        target.write_bytes(data)
        saved.append(rel_posix(s.docs_root, target))
    return {"saved": saved}


@router.get("/preview")
def preview(request: Request, path: str, chars: int = 3000) -> dict:
    """First `chars` characters of a document (used by the Label page)."""
    from app.core.extractors import extract

    s = request.app.state.container.settings
    target = safe_resolve(s.docs_root, path)
    if not target.is_file() or ext_of(target.name) not in s.extensions:
        raise AppError("NOT_FOUND", "File not found", 404)
    try:
        text = extract(target).text
    except Exception as exc:  # noqa: BLE001
        raise AppError("EXTRACT_FAILED", f"Cannot read this file: {type(exc).__name__}", 422) from exc
    return {"rel_path": rel_posix(s.docs_root, target), "text": text[:chars], "truncated": len(text) > chars}


@router.get("/download")
def download(request: Request, path: str):
    """Download a document or generated report (path-safe, allow-listed extensions only)."""
    from fastapi.responses import FileResponse

    s = request.app.state.container.settings
    target = safe_resolve(s.docs_root, path)
    if not target.is_file() or ext_of(target.name) not in s.extensions:
        raise AppError("NOT_FOUND", "File not found", 404)
    return FileResponse(target, filename=target.name)
