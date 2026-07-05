"""set_id parsing, set homes, canonical variant naming.

Numbering is computed over the UNION of a scan of the set's history dirs and
the ledger's add_variant entries for the set — generated sets span dates, so a
single-folder scan is not enough.
"""

from __future__ import annotations

import re
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
GENERATED_KINDS = {"lineart", "final"}
REFERENCE_KINDS = {"cast", "look-and-feel", "brand", "location"}
KNOWN_KINDS = GENERATED_KINDS | REFERENCE_KINDS

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class NamingError(Exception):
    pass


def parse_set_id(set_id: str) -> "tuple[str, str]":
    if not isinstance(set_id, str) or set_id.count("/") != 1:
        raise NamingError(f"set_id must be '<kind>/<name>', got {set_id!r}")
    kind, name = set_id.split("/")
    if kind not in KNOWN_KINDS:
        raise NamingError(f"unknown kind {kind!r}; known: {sorted(KNOWN_KINDS)}")
    if not _NAME_RE.match(name):
        raise NamingError(
            f"invalid set name {name!r} (lowercase letters/digits/._-, "
            f"must start with letter/digit)")
    return kind, name


def set_home(media: Path, kind: str, name: str, date: "str | None" = None) -> Path:
    if kind in REFERENCE_KINDS:
        return Path(media) / "references" / kind / name
    from .media import today
    return Path(media) / "generated" / (date or today()) / name


def set_history_dirs(media: Path, kind: str, name: str) -> "list[Path]":
    if kind in REFERENCE_KINDS:
        d = Path(media) / "references" / kind / name
        return [d] if d.is_dir() else []
    root = Path(media) / "generated"
    if not root.is_dir():
        return []
    return sorted(d / name for d in root.iterdir() if (d / name).is_dir())


def variant_stem(kind: str, name: str, stage: "str | None" = None) -> str:
    if kind in GENERATED_KINDS:
        return stage or kind
    return name


def pattern(kind: str, stem: str) -> "re.Pattern":
    exts = "|".join(e.lstrip(".") for e in IMAGE_EXTS)
    if kind in GENERATED_KINDS:
        return re.compile(rf"^{re.escape(stem)}-v(\d+)\.(?:{exts})$", re.I)
    return re.compile(rf"^{re.escape(stem)}-(\d+)\.(?:{exts})$", re.I)


def next_index(media: Path, kind: str, name: str, stem: str,
               ledger: "list[dict]", set_id: str) -> int:
    pat = pattern(kind, stem)
    highest = 0
    for d in set_history_dirs(media, kind, name):
        for p in d.iterdir():
            m = pat.match(p.name)
            if m:
                highest = max(highest, int(m.group(1)))
    for rec in ledger:
        if rec.get("op") == "add_variant" and rec.get("set_id") == set_id:
            m = pat.match(Path(rec.get("path", "")).name)
            if m:
                highest = max(highest, int(m.group(1)))
    return highest + 1


def canonical_name(kind: str, stem: str, index: int, ext: str) -> str:
    ext = ext.lower()
    if kind in GENERATED_KINDS:
        return f"{stem}-v{index}{ext}"
    return f"{stem}-{index:02d}{ext}"


def stems_for_set(kind: str, ledger: "list[dict]", set_id: str) -> "set[str]":
    stems: "set[str]" = {kind} if kind in GENERATED_KINDS else set()
    for rec in ledger:
        if rec.get("op") == "add_variant" and rec.get("set_id") == set_id:
            stage = rec.get("stage")
            if stage:
                stems.add(stage)
    return stems
