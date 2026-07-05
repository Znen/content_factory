"""Curation ops: variant sets + movable winner. Non-destructive by construction.

Every op returns a plain dict; failures are {"error": ..., "hint": ...} — no raw
tracebacks across the MCP boundary. History (references/, generated/) is
immutable: nothing here renames, moves or overwrites history files; the only
removal is discard() -> media/_TO_PURGE/ (soft, copy-verified).
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from . import naming
from .curate_state import (CurateStateError, append_ledger, load_manifest,
                           media_root, now_iso, read_ledger, save_manifest)

WINNERS_DIR = "winners"
PURGE_DIR = "_TO_PURGE"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _err(error: str, hint: str = "") -> dict:
    out = {"error": error}
    if hint:
        out["hint"] = hint
    return out


def _resolve_in_media(media: Path, p: "str | Path") -> "Path | None":
    """Absolute or media-relative -> absolute path strictly inside media, else None."""
    cand = Path(p)
    if not cand.is_absolute():
        cand = media / cand
    try:
        cand = cand.resolve()
        cand.relative_to(Path(media).resolve())
    except (ValueError, OSError):
        return None
    return cand


def _rel(media: Path, p: Path) -> str:
    return Path(p).resolve().relative_to(Path(media).resolve()).as_posix()


def _unique(dir_: Path, filename: str) -> Path:
    cand = dir_ / filename
    if not cand.exists():
        return cand
    stem, suf = Path(filename).stem, Path(filename).suffix
    i = 1
    while (dir_ / f"{stem}_{i}{suf}").exists():
        i += 1
    return dir_ / f"{stem}_{i}{suf}"


def _copy_verified(src: Path, dest: Path) -> "str | None":
    """copy2 + sha256 verify. Returns hash; None on I/O failure or mismatch
    (any partial/bad copy is removed; source is never touched)."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        h_src, h_dst = _sha256(src), _sha256(dest)
    except OSError:
        dest.unlink(missing_ok=True)
        return None
    if h_src != h_dst:
        dest.unlink(missing_ok=True)
        return None
    return h_dst


def add_variant(project: str, image_path: str, set_id: str, note: str = "",
                date: "str | None" = None, stage: "str | None" = None) -> dict:
    """Copy an image into a set's home under a canonical name. Source untouched."""
    project_dir = Path(project)
    media = media_root(project_dir)
    try:
        kind, name = naming.parse_set_id(set_id)
    except naming.NamingError as e:
        return _err(str(e), "set_id = '<kind>/<name>', e.g. 'cast/kurtukova'")
    src = Path(image_path)
    if not src.is_file():
        return _err(f"source not found: {image_path}")
    ext = src.suffix.lower()
    if ext not in naming.IMAGE_EXTS:
        return _err(f"unsupported image type {ext!r}",
                    f"supported: {sorted(naming.IMAGE_EXTS)}")
    if stage is not None and kind not in naming.GENERATED_KINDS:
        return _err("stage is only valid for lineart/final sets")
    ledger = read_ledger(project_dir)
    stem = naming.variant_stem(kind, name, stage)
    idx = naming.next_index(media, kind, name, stem, ledger, set_id)
    home = naming.set_home(media, kind, name, date)
    dest = _unique(home, naming.canonical_name(kind, stem, idx, ext))
    h = _copy_verified(src, dest)
    if h is None:
        return _err("copy failed (I/O error or hash mismatch) — source preserved, copy removed",
                    "retry; check disk space/permissions")
    rec = {"op": "add_variant", "set_id": set_id, "path": _rel(media, dest),
           "original_name": src.name, "source_path": str(src.resolve()),
           "sha256": h, "note": note}
    if stage:
        rec["stage"] = stage
    append_ledger(project_dir, rec)
    return {"set_id": set_id, "path": _rel(media, dest),
            "original_name": src.name, "sha256": h}
