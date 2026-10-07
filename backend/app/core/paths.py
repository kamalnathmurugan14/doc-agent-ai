"""Safe path helpers. EVERY user-supplied path must go through safe_resolve()."""

import re
import unicodedata
from pathlib import Path

from app.errors import AppError


def safe_resolve(root: Path, rel: str | Path = "") -> Path:
    """Resolve `rel` under `root`; reject traversal, absolute paths and escaping symlinks."""
    root_r = root.resolve()
    rel_s = str(rel).replace("\\", "/")
    if rel_s.startswith("/") or re.match(r"^[A-Za-z]:", rel_s) or "\x00" in rel_s:
        raise AppError("PATH_FORBIDDEN", "Absolute or invalid paths are not allowed", 400)
    target = (root_r / rel_s).resolve()  # resolve() follows symlinks, so escapes are caught here
    if target != root_r and root_r not in target.parents:
        raise AppError("PATH_FORBIDDEN", "Path is outside the documents folder", 400)
    return target


def rel_posix(root: Path, path: Path) -> str:
    """Relative path with forward slashes (stable across Windows/macOS/Linux)."""
    return path.resolve().relative_to(root.resolve()).as_posix()


def sanitize_filename(name: str) -> str:
    """Keep only the base name and safe characters."""
    name = unicodedata.normalize("NFKC", name.replace("\\", "/").split("/")[-1]).strip()
    name = re.sub(r"[^\w.\- ]", "_", name).strip(". ")
    if not name:
        raise AppError("BAD_FILENAME", "Invalid file name", 400)
    return name[:150]


def ext_of(name: str) -> str:
    return Path(name).suffix.lower().lstrip(".")
