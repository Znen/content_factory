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


def _projection_path(media: Path, kind: str, name: str, ext: str) -> Path:
    return media / WINNERS_DIR / kind / f"{name}{ext.lower()}"


def set_winner(project: str, set_id: str, image_path: str) -> dict:
    """Move the winner pointer: manifest (atomic) + refresh projection. No pixel moves."""
    project_dir = Path(project)
    media = media_root(project_dir)
    try:
        kind, name = naming.parse_set_id(set_id)
    except naming.NamingError as e:
        return _err(str(e))
    target = _resolve_in_media(media, image_path)
    if target is None or not target.is_file():
        return _err(f"winner target must be an existing file inside {media}",
                    "add it with gf_add_variant, or check gf_list_sets")
    rel_check = _rel(media, target)
    top = rel_check.split("/", 1)[0]
    if top in (WINNERS_DIR, PURGE_DIR):
        return _err(f"winner target must be a history file, not inside {top}/",
                    "point at the original under generated/ or references/ (see gf_list_sets)")
    try:
        manifest = load_manifest(project_dir)
    except CurateStateError as e:
        return _err(str(e))
    rel = _rel(media, target)
    entry = manifest["winners"].get(set_id)
    prev = entry["path"] if entry else None
    if prev == rel:
        return {"set_id": set_id, "path": rel, "changed": False}
    history = list(entry.get("history", [])) if entry else []
    if prev:
        history.append(prev)
    manifest["winners"][set_id] = {"path": rel, "set_at": now_iso(),
                                   "history": history}
    save_manifest(project_dir, manifest)
    append_ledger(project_dir, {"op": "set_winner", "set_id": set_id,
                                "path": rel, "prev": prev})
    result = {"set_id": set_id, "path": rel, "prev": prev, "changed": True}
    try:
        proj_dir = media / WINNERS_DIR / kind
        proj_dir.mkdir(parents=True, exist_ok=True)
        for old in proj_dir.iterdir():
            if old.is_file() and old.stem == name:
                old.unlink()
        proj = _projection_path(media, kind, name, target.suffix)
        shutil.copy2(target, proj)
        result["projection"] = _rel(media, proj)
    except OSError as e:
        result["projection_error"] = f"projection refresh failed: {e}"
        result["hint"] = "run gf_materialize_winners to rebuild winners/"
    return result


def materialize_winners(project: str) -> dict:
    """Rebuild winners/ projection from manifest + history. Projection is disposable."""
    project_dir = Path(project)
    media = media_root(project_dir)
    try:
        manifest = load_manifest(project_dir)
    except CurateStateError as e:
        return _err(str(e))
    expected: "set[Path]" = set()
    materialized, dangling = 0, []
    for set_id, entry in manifest["winners"].items():
        try:
            kind, name = naming.parse_set_id(set_id)
        except naming.NamingError:
            dangling.append(set_id)
            continue
        src = media / entry.get("path", "")
        if not src.is_file():
            dangling.append(set_id)
            continue
        proj = _projection_path(media, kind, name, src.suffix)
        try:
            proj.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, proj)
        except OSError:
            dangling.append(set_id)
            continue
        expected.add(proj.resolve())
        materialized += 1
    removed = 0
    wdir = media / WINNERS_DIR
    if wdir.is_dir():
        for p in wdir.rglob("*"):
            if p.is_file() and p.resolve() not in expected:
                try:
                    p.unlink()
                except OSError:
                    continue
                removed += 1
    return {"materialized": materialized, "removed_stale": removed,
            "dangling": sorted(dangling)}


def adopt_set(project: str, set_id: str, dir: str) -> dict:
    """Register an existing directory as a set's history (ledger only; no moves)."""
    project_dir = Path(project)
    media = media_root(project_dir)
    try:
        naming.parse_set_id(set_id)
    except naming.NamingError as e:
        return _err(str(e))
    d = _resolve_in_media(media, dir)
    if d is None or not d.is_dir():
        return _err(f"dir must be an existing directory inside {media}")
    files = sum(1 for p in d.iterdir()
                if p.is_file() and p.suffix.lower() in naming.IMAGE_EXTS)
    rel_dir = _rel(media, d)
    append_ledger(project_dir, {"op": "adopt", "set_id": set_id,
                                "dir": rel_dir, "files": files})
    return {"set_id": set_id, "dir": rel_dir, "files": files}


def list_sets(project: str, kind: "str | None" = None) -> dict:
    """Inventory: sets (manifest ∪ ledger ∪ references scan), counts, winners."""
    project_dir = Path(project)
    media = media_root(project_dir)
    try:
        manifest = load_manifest(project_dir)
    except CurateStateError as e:
        return _err(str(e))
    ledger = read_ledger(project_dir)

    ids: "set[str]" = set(manifest["winners"])
    for rec in ledger:
        sid = rec.get("set_id")
        if sid:
            ids.add(sid)
    refs = media / "references"
    if refs.is_dir():
        for kdir in refs.iterdir():
            if kdir.is_dir() and kdir.name in naming.REFERENCE_KINDS:
                for ndir in kdir.iterdir():
                    if ndir.is_dir():
                        ids.add(f"{kdir.name}/{ndir.name}")

    adopted = {rec["set_id"]: rec.get("dir") for rec in ledger
               if rec.get("op") == "adopt" and rec.get("set_id")}
    sets = []
    for set_id in sorted(ids):
        try:
            k, name = naming.parse_set_id(set_id)
        except naming.NamingError:
            continue
        if kind and k != kind:
            continue
        dirs = naming.set_history_dirs(media, k, name)
        ad = adopted.get(set_id)
        if ad:
            adp = media / ad
            if adp.is_dir() and adp not in dirs:
                dirs = dirs + [adp]
        if k in naming.REFERENCE_KINDS:
            variants = sum(1 for d in dirs for p in d.iterdir()
                           if p.is_file() and p.suffix.lower() in naming.IMAGE_EXTS)
        else:
            stems = naming.stems_for_set(k, ledger, set_id)
            pats = [naming.pattern(k, s) for s in stems]
            variants = sum(1 for d in dirs for p in d.iterdir()
                           if p.is_file() and any(pt.match(p.name) for pt in pats))
        entry = manifest["winners"].get(set_id)
        winner = entry["path"] if entry else None
        sets.append({"set_id": set_id, "kind": k, "name": name,
                     "variants": variants, "winner": winner,
                     "winner_exists": bool(winner) and (media / winner).is_file(),
                     "dirs": [_rel(media, d) for d in dirs]})
    return {"sets": sets}
