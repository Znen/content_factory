# Media Curation Core (Ф2a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the curation core to content-factory — variant sets + movable winner (manifest + ledger + canonical naming) exposed as six non-destructive MCP tools (`gf_add_variant`, `gf_set_winner`, `gf_list_sets`, `gf_materialize_winners`, `gf_discard`, `gf_adopt_set`) with CLI mirrors.

**Architecture:** Three new modules layered bottom-up: `gf/curate_state.py` (atomic winners-manifest I/O + append-only ledger), `gf/naming.py` (set_id parsing, set homes, canonical variant numbering over union of dir scan + ledger), `gf/curate.py` (the six operations, each returning a plain dict; failures are `{"error","hint"}`). `mcp_server.py` and `cli.py` wrap them thinly. Everything is pure filesystem + stdlib — no network, no new dependencies (Pillow comes only in Ф2b with `gf_contact_sheet`).

**Tech Stack:** Python ≥3.10, stdlib only (json, hashlib, shutil, os.replace, re, pathlib). pytest with tmp_path. Spec: `docs/superpowers/specs/2026-07-05-media-curation-routing-design.md`.

## Global Constraints

- Package `gf`, env prefix `GF_` — no new config keys needed for Ф2a. NO new dependencies (Pillow deferred to Ф2b).
- **History is immutable:** no op renames, moves, or overwrites files in `references/` or `generated/`. The only removal is `discard()` → `media/_TO_PURGE/<YYYY-MM-DD>/` (copy→sha256→remove; hard-delete does not exist in the API).
- **Every copy is verified:** copy2 → sha256 compare; mismatch → copy removed, source preserved, error returned.
- **No overwrites in history:** name collision → auto-suffix `_1`, `_2`… Only projections (`winners/`, later `contact-sheets/`) are replaceable.
- **Manifest** `media/.gf_winners.json` — atomic write (tmp + `os.replace`); shape `{"version":1,"winners":{"<set_id>":{"path","set_at","history":[...]}}}`. Paths are POSIX relpaths from `media/`.
- **Ledger** `media/.gf_media_ledger.jsonl` — append-only, never edited; malformed lines skipped on read (pattern from Phase 1 `budget.spent`).
- **set_id** = `<kind>/<name>`; kinds: generated `lineart|final` (history in `generated/<date>/<name>/`, may span dates), reference `cast|look-and-feel|brand|location` (history in `references/<kind>/<name>/`). Name charset `[a-z0-9][a-z0-9._-]*`.
- **Canonical names:** reference variants `<name>-NN.<ext>` (zero-padded 2); generated iterations `<stem>-vN.<ext>` where stem = `stage` param or kind. Numbering = max over (scan of set history dirs) ∪ (ledger `add_variant` entries for the set) + 1.
- **Image extensions:** `{.png,.jpg,.jpeg,.webp}` (aligned with nano backend).
- **Errors are structured dicts** `{"error": str, "hint": str?}` — never raw tracebacks across the MCP boundary.
- All destination paths validated strictly inside `<project>/media/` (traversal-safe); `add_variant` source may be anywhere but is read-only.
- Windows: run tests with `python -m pytest`; UTF-8 everywhere (`encoding="utf-8"`).

---

## File Structure

```
gf/
├── curate_state.py    NEW — manifest load/save (atomic) + ledger append/read
├── naming.py          NEW — parse_set_id, set_home, set_history_dirs, pattern,
│                            next_index, canonical_name, variant_stem, stems_for_set
├── curate.py          NEW — add_variant, set_winner, list_sets,
│                            materialize_winners, discard, adopt_set
├── mcp_server.py      MODIFY — register 6 tools in build_server()
└── cli.py             MODIFY — 6 CLI mirrors
tests/
├── test_curate_state.py  NEW
├── test_naming.py        NEW
├── test_curate.py        NEW (ops; grows across Tasks 3-6)
├── test_mcp.py           MODIFY (tool registration)
└── test_cli.py           MODIFY (help lists new commands)
```

---

### Task 1: State layer (`curate_state.py`)

**Files:**
- Create: `gf/curate_state.py`
- Test: `tests/test_curate_state.py`

**Interfaces:**
- Consumes: nothing from other gf modules.
- Produces (Tasks 3-6 rely on these exact signatures):
  - `CurateStateError(Exception)`
  - `media_root(project_dir: Path) -> Path` → `<project>/media`
  - `now_iso() -> str` (UTC ISO)
  - `load_manifest(project_dir: Path) -> dict` (default `{"version":1,"winners":{}}`; raises `CurateStateError` with recovery hint on corrupt/malformed)
  - `save_manifest(project_dir: Path, manifest: dict) -> None` (atomic tmp+`os.replace`)
  - `append_ledger(project_dir: Path, record: dict) -> None` (auto-adds `ts`)
  - `read_ledger(project_dir: Path) -> list[dict]` (skips malformed/non-dict lines)
  - Constants `MANIFEST_NAME = ".gf_winners.json"`, `LEDGER_NAME = ".gf_media_ledger.jsonl"`

- [ ] **Step 1: Write the failing test** `tests/test_curate_state.py`

```python
import json
import pytest
from gf.curate_state import (CurateStateError, append_ledger, load_manifest,
                             read_ledger, save_manifest)


def test_load_manifest_default_when_missing(tmp_path):
    assert load_manifest(tmp_path) == {"version": 1, "winners": {}}


def test_save_load_roundtrip_atomic(tmp_path):
    m = {"version": 1, "winners": {"cast/kurtukova": {
        "path": "references/cast/kurtukova/kurtukova-05.jpg",
        "set_at": "2026-07-05T00:00:00+00:00", "history": []}}}
    save_manifest(tmp_path, m)
    assert load_manifest(tmp_path) == m
    assert not list((tmp_path / "media").glob("*.tmp"))  # no tmp litter


def test_corrupt_manifest_raises_with_recovery_hint(tmp_path):
    p = tmp_path / "media" / ".gf_winners.json"
    p.parent.mkdir(parents=True)
    p.write_text("{broken", encoding="utf-8")
    with pytest.raises(CurateStateError) as ei:
        load_manifest(tmp_path)
    assert "ledger" in str(ei.value).lower()


def test_malformed_manifest_shape_raises(tmp_path):
    p = tmp_path / "media" / ".gf_winners.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps([1, 2]), encoding="utf-8")
    with pytest.raises(CurateStateError):
        load_manifest(tmp_path)


def test_ledger_append_adds_ts_and_read_skips_garbage(tmp_path):
    append_ledger(tmp_path, {"op": "adopt", "set_id": "cast/a",
                             "dir": "references/cast/a", "files": 2})
    lp = tmp_path / "media" / ".gf_media_ledger.jsonl"
    with lp.open("a", encoding="utf-8") as fh:
        fh.write("not json\n123\n\n")
    recs = read_ledger(tmp_path)
    assert len(recs) == 1
    assert recs[0]["op"] == "adopt" and "ts" in recs[0]


def test_read_ledger_empty_when_missing(tmp_path):
    assert read_ledger(tmp_path) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_curate_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gf.curate_state'`

- [ ] **Step 3: Write `gf/curate_state.py`**

```python
"""Winners manifest + media ledger I/O.

Owns media/.gf_winners.json (truth of winner pointers; atomic writes) and
media/.gf_media_ledger.jsonl (append-only operation journal; never edited).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_NAME = ".gf_winners.json"
LEDGER_NAME = ".gf_media_ledger.jsonl"


class CurateStateError(Exception):
    """Manifest unreadable or malformed; message carries a recovery hint."""


def media_root(project_dir: Path) -> Path:
    return Path(project_dir) / "media"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _manifest_path(project_dir: Path) -> Path:
    return media_root(project_dir) / MANIFEST_NAME


def _ledger_path(project_dir: Path) -> Path:
    return media_root(project_dir) / LEDGER_NAME


def load_manifest(project_dir: Path) -> dict:
    path = _manifest_path(project_dir)
    if not path.exists():
        return {"version": 1, "winners": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise CurateStateError(
            f"manifest corrupt: {path} ({e}); recover by replaying the last "
            f"set_winner per set_id from {LEDGER_NAME}") from e
    if not isinstance(data, dict) or not isinstance(data.get("winners"), dict):
        raise CurateStateError(
            f"manifest malformed: {path}; recover from {LEDGER_NAME}")
    return data


def save_manifest(project_dir: Path, manifest: dict) -> None:
    path = _manifest_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, path)


def append_ledger(project_dir: Path, record: dict) -> None:
    path = _ledger_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": now_iso(), **record}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_ledger(project_dir: Path) -> "list[dict]":
    path = _ledger_path(project_dir)
    if not path.exists():
        return []
    out: "list[dict]" = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_curate_state.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
cd R:/Dev/tools/content-factory
git add gf/curate_state.py tests/test_curate_state.py
git commit -m "feat: curation state layer — atomic winners manifest + append-only ledger"
```

---

### Task 2: Naming layer (`naming.py`)

**Files:**
- Create: `gf/naming.py`
- Test: `tests/test_naming.py`

**Interfaces:**
- Consumes: `gf.media.today()` (Phase 1).
- Produces (Tasks 3-6 rely on these exact signatures):
  - `NamingError(Exception)`
  - `IMAGE_EXTS = {".png",".jpg",".jpeg",".webp"}`; `GENERATED_KINDS = {"lineart","final"}`; `REFERENCE_KINDS = {"cast","look-and-feel","brand","location"}`
  - `parse_set_id(set_id: str) -> tuple[str, str]` (raises `NamingError`)
  - `set_home(media: Path, kind: str, name: str, date: str | None = None) -> Path`
  - `set_history_dirs(media: Path, kind: str, name: str) -> list[Path]` (generated sets span dates)
  - `variant_stem(kind: str, name: str, stage: str | None = None) -> str`
  - `pattern(kind: str, stem: str) -> re.Pattern` (matches canonical variant filenames)
  - `next_index(media, kind, name, stem, ledger: list[dict], set_id: str) -> int`
  - `canonical_name(kind: str, stem: str, index: int, ext: str) -> str`
  - `stems_for_set(kind: str, ledger: list[dict], set_id: str) -> set[str]`

- [ ] **Step 1: Write the failing test** `tests/test_naming.py`

```python
import pytest
from gf import naming


def test_parse_set_id_ok():
    assert naming.parse_set_id("cast/kurtukova") == ("cast", "kurtukova")
    assert naming.parse_set_id("lineart/shot-02") == ("lineart", "shot-02")


@pytest.mark.parametrize("bad", ["cast", "cast/", "/x", "nope/x",
                                 "cast/UPPER", "cast/a/b", "lineart/-x"])
def test_parse_set_id_rejects(bad):
    with pytest.raises(naming.NamingError):
        naming.parse_set_id(bad)


def test_set_home_reference(tmp_path):
    assert naming.set_home(tmp_path, "cast", "kurtukova") == \
        tmp_path / "references" / "cast" / "kurtukova"


def test_set_home_generated_uses_explicit_date(tmp_path):
    assert naming.set_home(tmp_path, "lineart", "shot-02", date="2026-07-05") == \
        tmp_path / "generated" / "2026-07-05" / "shot-02"


def test_history_dirs_span_dates(tmp_path):
    for d in ["2026-07-04", "2026-07-05"]:
        (tmp_path / "generated" / d / "shot-02").mkdir(parents=True)
    (tmp_path / "generated" / "storyboard").mkdir()  # non-date dir without the set
    dirs = naming.set_history_dirs(tmp_path, "lineart", "shot-02")
    assert [d.parent.name for d in dirs] == ["2026-07-04", "2026-07-05"]


def test_next_index_union_of_scan_and_ledger(tmp_path):
    (tmp_path / "generated" / "2026-07-04" / "shot-02").mkdir(parents=True)
    (tmp_path / "generated" / "2026-07-05" / "shot-02").mkdir(parents=True)
    (tmp_path / "generated" / "2026-07-04" / "shot-02" / "lineart-v1.png").write_bytes(b"x")
    (tmp_path / "generated" / "2026-07-05" / "shot-02" / "lineart-v3.png").write_bytes(b"x")
    ledger = [{"op": "add_variant", "set_id": "lineart/shot-02",
               "path": "generated/2026-07-03/shot-02/lineart-v7.png"}]
    assert naming.next_index(tmp_path, "lineart", "shot-02", "lineart",
                             ledger, "lineart/shot-02") == 8


def test_next_index_reference_ignores_unrelated(tmp_path):
    d = tmp_path / "references" / "cast" / "kurtukova"
    d.mkdir(parents=True)
    (d / "kurtukova-05.jpg").write_bytes(b"x")
    (d / "unrelated.png").write_bytes(b"x")
    assert naming.next_index(tmp_path, "cast", "kurtukova", "kurtukova",
                             [], "cast/kurtukova") == 6


def test_canonical_names():
    assert naming.canonical_name("cast", "kurtukova", 7, ".jpg") == "kurtukova-07.jpg"
    assert naming.canonical_name("final", "magnific", 6, ".PNG") == "magnific-v6.png"


def test_variant_stem():
    assert naming.variant_stem("lineart", "shot-02") == "lineart"
    assert naming.variant_stem("final", "shot-02", stage="magnific") == "magnific"
    assert naming.variant_stem("cast", "kurtukova") == "kurtukova"


def test_stems_for_set_includes_ledger_stages():
    ledger = [{"op": "add_variant", "set_id": "final/shot-02",
               "path": "generated/2026-07-05/shot-02/magnific-v1.png",
               "stage": "magnific"}]
    assert naming.stems_for_set("final", ledger, "final/shot-02") == \
        {"final", "magnific"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_naming.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gf.naming'`

- [ ] **Step 3: Write `gf/naming.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_naming.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
cd R:/Dev/tools/content-factory
git add gf/naming.py tests/test_naming.py
git commit -m "feat: naming layer — set_id, homes, canonical variant numbering"
```

---

### Task 3: `curate.add_variant`

**Files:**
- Create: `gf/curate.py`
- Test: `tests/test_curate.py` (new file; grows in Tasks 4-6)

**Interfaces:**
- Consumes: Task 1 (`curate_state`), Task 2 (`naming`).
- Produces:
  - Module scaffolding used by Tasks 4-6: `_sha256`, `_err`, `_resolve_in_media`, `_rel`, `_unique`, `_copy_verified`, constants `WINNERS_DIR = "winners"`, `PURGE_DIR = "_TO_PURGE"`.
  - `add_variant(project: str, image_path: str, set_id: str, note: str = "", date: str | None = None, stage: str | None = None) -> dict` — success: `{"set_id","path","original_name","sha256"}` (path = POSIX relpath from media).

- [ ] **Step 1: Write the failing test** `tests/test_curate.py`

```python
from pathlib import Path
import pytest
from gf import curate
from gf.curate_state import load_manifest, read_ledger


def _proj(tmp_path):
    (tmp_path / "media").mkdir(exist_ok=True)
    return tmp_path


def _img(dir_: Path, name="src.png", data=b"PNGDATA"):
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / name
    p.write_bytes(data)
    return p


def test_add_variant_reference_copies_renames_ledgers(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "incoming", "IMG_4211.jpg", b"JPGDATA")
    out = curate.add_variant(str(proj), str(src), "cast/kurtukova", note="из брифа")
    assert "error" not in out
    assert out["path"] == "references/cast/kurtukova/kurtukova-01.jpg"
    assert (proj / "media" / out["path"]).read_bytes() == b"JPGDATA"
    assert src.exists()  # source untouched
    rec = read_ledger(proj)[-1]
    assert rec["op"] == "add_variant" and rec["original_name"] == "IMG_4211.jpg"
    assert rec["note"] == "из брифа" and rec["sha256"] == out["sha256"]


def test_add_variant_generated_uses_date_and_stage(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "x.png")
    out = curate.add_variant(str(proj), str(src), "final/shot-02",
                             date="2026-07-05", stage="magnific")
    assert out["path"] == "generated/2026-07-05/shot-02/magnific-v1.png"
    assert read_ledger(proj)[-1]["stage"] == "magnific"


def test_add_variant_numbering_continues_across_calls(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png")
    curate.add_variant(str(proj), str(src), "lineart/shot-01", date="2026-07-05")
    out2 = curate.add_variant(str(proj), str(src), "lineart/shot-01", date="2026-07-05")
    assert out2["path"].endswith("/lineart-v2.png")


def test_add_variant_hash_mismatch_keeps_source_removes_copy(tmp_path, monkeypatch):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png")
    hashes = iter(["aaa", "bbb"])
    monkeypatch.setattr(curate, "_sha256", lambda p: next(hashes))
    out = curate.add_variant(str(proj), str(src), "cast/anna")
    assert "error" in out and "hash" in out["error"].lower()
    assert src.exists()
    home = proj / "media" / "references" / "cast" / "anna"
    assert not home.exists() or not any(home.iterdir())


def test_add_variant_validation_errors(tmp_path):
    proj = _proj(tmp_path)
    gif = _img(tmp_path / "in", "a.gif", b"GIF")
    assert "error" in curate.add_variant(str(proj), str(gif), "cast/anna")
    png = _img(tmp_path / "in", "b.png")
    assert "error" in curate.add_variant(str(proj), str(png), "wat/anna")
    assert "error" in curate.add_variant(str(proj), str(png), "cast/anna", stage="x")
    assert "error" in curate.add_variant(str(proj), str(tmp_path / "nope.png"), "cast/anna")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_curate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gf.curate'`

- [ ] **Step 3: Write `gf/curate.py`**

```python
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
    """copy2 + sha256 verify. Returns hash, or None on mismatch (copy removed)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    h_src, h_dst = _sha256(src), _sha256(dest)
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
        return _err("hash mismatch after copy — source preserved, copy removed",
                    "retry; check disk health")
    rec = {"op": "add_variant", "set_id": set_id, "path": _rel(media, dest),
           "original_name": src.name, "source_path": str(src),
           "sha256": h, "note": note}
    if stage:
        rec["stage"] = stage
    append_ledger(project_dir, rec)
    return {"set_id": set_id, "path": _rel(media, dest),
            "original_name": src.name, "sha256": h}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_curate.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
cd R:/Dev/tools/content-factory
git add gf/curate.py tests/test_curate.py
git commit -m "feat: curate.add_variant — verified copy into set home, canonical name, ledger"
```

---

### Task 4: `curate.set_winner` + `curate.materialize_winners`

**Files:**
- Modify: `gf/curate.py` (append functions)
- Test: `tests/test_curate.py` (append tests)

**Interfaces:**
- Consumes: Task 3 scaffolding (`_resolve_in_media`, `_rel`, `_err`), Tasks 1-2.
- Produces:
  - `set_winner(project: str, set_id: str, image_path: str) -> dict` — success: `{"set_id","path","prev","changed","projection"}`; idempotent re-set returns `{"set_id","path","changed": False}`.
  - `materialize_winners(project: str) -> dict` — `{"materialized": int, "removed_stale": int, "dangling": [set_id,...]}`.
  - `_projection_path(media, kind, name, ext) -> Path` (used by both).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_curate.py`)

```python
def test_set_winner_updates_manifest_and_projection(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png")
    added = curate.add_variant(str(proj), str(src), "lineart/shot-01", date="2026-07-05")
    out = curate.set_winner(str(proj), "lineart/shot-01", added["path"])
    assert out["changed"] is True and out["prev"] is None
    m = load_manifest(proj)
    assert m["winners"]["lineart/shot-01"]["path"] == added["path"]
    assert (proj / "media" / "winners" / "lineart" / "shot-01.png").exists()
    assert read_ledger(proj)[-1]["op"] == "set_winner"


def test_set_winner_reassign_appends_history_and_is_idempotent(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png")
    v1 = curate.add_variant(str(proj), str(src), "lineart/shot-01", date="2026-07-05")
    v2 = curate.add_variant(str(proj), str(src), "lineart/shot-01", date="2026-07-05")
    curate.set_winner(str(proj), "lineart/shot-01", v1["path"])
    out = curate.set_winner(str(proj), "lineart/shot-01", v2["path"])
    assert out["prev"] == v1["path"]
    assert load_manifest(proj)["winners"]["lineart/shot-01"]["history"] == [v1["path"]]
    again = curate.set_winner(str(proj), "lineart/shot-01", v2["path"])
    assert again["changed"] is False


def test_set_winner_rejects_missing_or_outside(tmp_path):
    proj = _proj(tmp_path)
    assert "error" in curate.set_winner(str(proj), "lineart/shot-01", "generated/nope.png")
    outside = _img(tmp_path / "elsewhere", "x.png")
    assert "error" in curate.set_winner(str(proj), "lineart/shot-01", str(outside))


def test_materialize_rebuilds_and_cleans_stale(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png")
    added = curate.add_variant(str(proj), str(src), "cast/anna")
    curate.set_winner(str(proj), "cast/anna", added["path"])
    wdir = proj / "media" / "winners"
    (wdir / "cast" / "anna.png").unlink()          # проекцию испортили
    (wdir / "cast" / "stale.png").write_bytes(b"junk")
    out = curate.materialize_winners(str(proj))
    assert out["materialized"] == 1 and out["removed_stale"] == 1
    assert out["dangling"] == []
    assert (wdir / "cast" / "anna.png").exists()


def test_materialize_reports_dangling_winner(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png")
    added = curate.add_variant(str(proj), str(src), "cast/anna")
    curate.set_winner(str(proj), "cast/anna", added["path"])
    (proj / "media" / added["path"]).unlink()      # история потеряна извне
    out = curate.materialize_winners(str(proj))
    assert out["dangling"] == ["cast/anna"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_curate.py -v`
Expected: new tests FAIL — `AttributeError: module 'gf.curate' has no attribute 'set_winner'`

- [ ] **Step 3: Append to `gf/curate.py`**

```python
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
    proj_dir = media / WINNERS_DIR / kind
    proj_dir.mkdir(parents=True, exist_ok=True)
    for old in proj_dir.glob(f"{name}.*"):   # stale ext variants of this set
        old.unlink(missing_ok=True)
    proj = _projection_path(media, kind, name, target.suffix)
    shutil.copy2(target, proj)
    append_ledger(project_dir, {"op": "set_winner", "set_id": set_id,
                                "path": rel, "prev": prev})
    return {"set_id": set_id, "path": rel, "prev": prev, "changed": True,
            "projection": _rel(media, proj)}


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
        proj.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, proj)
        expected.add(proj.resolve())
        materialized += 1
    removed = 0
    wdir = media / WINNERS_DIR
    if wdir.is_dir():
        for p in wdir.rglob("*"):
            if p.is_file() and p.resolve() not in expected:
                p.unlink()
                removed += 1
    return {"materialized": materialized, "removed_stale": removed,
            "dangling": sorted(dangling)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_curate.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
cd R:/Dev/tools/content-factory
git add gf/curate.py tests/test_curate.py
git commit -m "feat: curate.set_winner + materialize_winners — movable pointer, disposable projection"
```

---

### Task 5: `curate.list_sets` + `curate.adopt_set`

**Files:**
- Modify: `gf/curate.py` (append functions)
- Test: `tests/test_curate.py` (append tests)

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces:
  - `adopt_set(project: str, set_id: str, dir: str) -> dict` — `{"set_id","dir","files"}`; only appends a ledger record, moves nothing.
  - `list_sets(project: str, kind: str | None = None) -> dict` — `{"sets": [{"set_id","kind","name","variants","winner","winner_exists","dirs"}]}`. Sets discovered from manifest ∪ ledger ∪ scan of `references/<known-kind>/*/`. Generated variant counts use `stems_for_set` patterns; adopted dirs are included via their ledger record.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_curate.py`)

```python
def test_adopt_registers_without_moving(tmp_path):
    proj = _proj(tmp_path)
    legacy = proj / "media" / "generated" / "2026-07-04" / "shot-03-kitchen"
    legacy.mkdir(parents=True)
    (legacy / "kitchen-birch-v1.jpg").write_bytes(b"x")
    (legacy / "kitchen-birch-v2.jpg").write_bytes(b"x")
    (legacy / "notes.txt").write_bytes(b"x")
    out = curate.adopt_set(str(proj), "final/shot-03-kitchen",
                           "generated/2026-07-04/shot-03-kitchen")
    assert out["files"] == 2                      # only images counted
    assert (legacy / "kitchen-birch-v1.jpg").exists()  # nothing moved
    assert read_ledger(proj)[-1]["op"] == "adopt"
    ids = [s["set_id"] for s in curate.list_sets(str(proj))["sets"]]
    assert "final/shot-03-kitchen" in ids


def test_adopt_rejects_outside_or_missing_dir(tmp_path):
    proj = _proj(tmp_path)
    assert "error" in curate.adopt_set(str(proj), "final/x", "generated/nope")
    assert "error" in curate.adopt_set(str(proj), "final/x", str(tmp_path / "elsewhere"))


def test_list_sets_discovers_reference_dirs_and_winner_flags(tmp_path):
    proj = _proj(tmp_path)
    d = proj / "media" / "references" / "cast" / "kurtukova"
    d.mkdir(parents=True)
    (d / "kurtukova-01.jpg").write_bytes(b"x")
    listed = curate.list_sets(str(proj), kind="cast")
    (s,) = listed["sets"]
    assert s["set_id"] == "cast/kurtukova"
    assert s["variants"] == 1 and s["winner"] is None
    curate.set_winner(str(proj), "cast/kurtukova",
                      "references/cast/kurtukova/kurtukova-01.jpg")
    listed = curate.list_sets(str(proj), kind="cast")
    assert listed["sets"][0]["winner_exists"] is True


def test_list_sets_counts_generated_by_stems(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png")
    curate.add_variant(str(proj), str(src), "final/shot-02",
                       date="2026-07-05", stage="magnific")
    curate.add_variant(str(proj), str(src), "final/shot-02", date="2026-07-05")
    curate.add_variant(str(proj), str(src), "lineart/shot-02", date="2026-07-05")
    sets = {s["set_id"]: s for s in curate.list_sets(str(proj))["sets"]}
    assert sets["final/shot-02"]["variants"] == 2      # magnific-v1 + final-v1
    assert sets["lineart/shot-02"]["variants"] == 1    # lineart-v1 only
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_curate.py -v`
Expected: new tests FAIL — `AttributeError: module 'gf.curate' has no attribute 'adopt_set'`

- [ ] **Step 3: Append to `gf/curate.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_curate.py -v`
Expected: PASS (14 passed)

- [ ] **Step 5: Commit**

```bash
cd R:/Dev/tools/content-factory
git add gf/curate.py tests/test_curate.py
git commit -m "feat: curate.list_sets + adopt_set — inventory and legacy adoption"
```

---

### Task 6: `curate.discard` (soft delete)

**Files:**
- Modify: `gf/curate.py` (append function)
- Test: `tests/test_curate.py` (append tests)

**Interfaces:**
- Consumes: Tasks 1-4 (`_copy_verified`, `_unique`, `_resolve_in_media`, `_rel`, manifest).
- Produces: `discard(project: str, image_path: str) -> dict` — success `{"moved_to","sha256"}` (+`"hint"` if a winner now dangles). Never hard-deletes; target must be inside `media/`; refuses files already in `_TO_PURGE`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_curate.py`)

```python
def test_discard_moves_to_purge_verified(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png", b"KEEP")
    added = curate.add_variant(str(proj), str(src), "cast/anna")
    out = curate.discard(str(proj), added["path"])
    assert "error" not in out
    moved = proj / "media" / out["moved_to"]
    assert moved.read_bytes() == b"KEEP"
    assert out["moved_to"].startswith("_TO_PURGE/")
    assert not (proj / "media" / added["path"]).exists()
    assert read_ledger(proj)[-1]["op"] == "discard"


def test_discard_blocks_outside_media_and_double_discard(tmp_path):
    proj = _proj(tmp_path)
    outside = _img(tmp_path / "elsewhere", "x.png")
    assert "error" in curate.discard(str(proj), str(outside))
    src = _img(tmp_path / "in", "a.png")
    added = curate.add_variant(str(proj), str(src), "cast/anna")
    moved = curate.discard(str(proj), added["path"])["moved_to"]
    assert "error" in curate.discard(str(proj), moved)  # already in _TO_PURGE


def test_discard_current_winner_warns_dangling(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png")
    added = curate.add_variant(str(proj), str(src), "cast/anna")
    curate.set_winner(str(proj), "cast/anna", added["path"])
    out = curate.discard(str(proj), added["path"])
    assert "hint" in out and "cast/anna" in out["hint"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_curate.py -v`
Expected: new tests FAIL — `AttributeError: module 'gf.curate' has no attribute 'discard'`

- [ ] **Step 3: Append to `gf/curate.py`**

```python
def discard(project: str, image_path: str) -> dict:
    """Soft delete: copy→sha256→remove into media/_TO_PURGE/<date>/. Never hard-delete."""
    project_dir = Path(project)
    media = media_root(project_dir)
    src = _resolve_in_media(media, image_path)
    if src is None or not src.is_file():
        return _err(f"file to discard must exist inside {media}",
                    "nothing outside the project media can be discarded")
    if PURGE_DIR in src.parts:
        return _err("already in _TO_PURGE")
    rel_src = _rel(media, src)
    dest = _unique(media / PURGE_DIR / now_iso()[:10], src.name)
    h = _copy_verified(src, dest)
    if h is None:
        return _err("hash mismatch — source preserved, nothing removed")
    src.unlink()
    rel_moved = _rel(media, dest)
    append_ledger(project_dir, {"op": "discard", "path": rel_src,
                                "moved_to": rel_moved, "sha256": h})
    out = {"moved_to": rel_moved, "sha256": h}
    try:
        manifest = load_manifest(project_dir)
        dangling = sorted(sid for sid, e in manifest["winners"].items()
                          if e.get("path") == rel_src)
        if dangling:
            out["hint"] = (f"winner now dangling for {dangling}; "
                           f"re-run gf_set_winner")
    except CurateStateError:
        pass
    return out
```

- [ ] **Step 4: Run tests to verify they pass, then full suite**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_curate.py -v && python -m pytest`
Expected: test_curate 17 passed; full suite green (~66 passed, 1 skipped: prior 32+1, plus 6 state + 11 naming + 17 curate). Counts are approximate — report the ACTUAL numbers; do not force them.

- [ ] **Step 5: Commit**

```bash
cd R:/Dev/tools/content-factory
git add gf/curate.py tests/test_curate.py
git commit -m "feat: curate.discard — soft delete via _TO_PURGE with dangling-winner hint"
```

---

### Task 7: MCP tools wiring

**Files:**
- Modify: `gf/mcp_server.py` (inside `build_server()`, after the two existing tools)
- Test: `tests/test_mcp.py` (append test)

**Interfaces:**
- Consumes: `gf.curate` (Tasks 3-6).
- Produces: MCP tools `gf_add_variant`, `gf_set_winner`, `gf_list_sets`, `gf_materialize_winners`, `gf_discard`, `gf_adopt_set` registered on the `generation-factory` server. JSON-friendly signatures: optional strings default `""` and are converted to `None`/kwargs internally.

- [ ] **Step 1: Write the failing test** (append to `tests/test_mcp.py`)

```python
def test_curation_tools_registered():
    import asyncio
    from gf.mcp_server import build_server
    mcp, _ = build_server()
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"gf_add_variant", "gf_set_winner", "gf_list_sets",
            "gf_materialize_winners", "gf_discard", "gf_adopt_set"} <= names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_mcp.py::test_curation_tools_registered -v`
Expected: FAIL — assertion (tools not registered yet)

- [ ] **Step 3: Modify `gf/mcp_server.py`** — inside `build_server()`, after the `gf_generate_final` tool definition and before `return mcp, settings`, add:

```python
    from . import curate

    @mcp.tool()
    def gf_add_variant(project: str, image_path: str, set_id: str,
                       note: str = "", date: str = "", stage: str = "") -> dict:
        """Copy an image into a variant set under a canonical name (source untouched).
        set_id = '<kind>/<name>', kinds: lineart|final|cast|look-and-feel|brand|location."""
        return curate.add_variant(project, image_path, set_id, note=note,
                                  date=date or None, stage=stage or None)

    @mcp.tool()
    def gf_set_winner(project: str, set_id: str, image_path: str) -> dict:
        """Point a set's movable winner at a file inside the project (no pixel moves)."""
        return curate.set_winner(project, set_id, image_path)

    @mcp.tool()
    def gf_list_sets(project: str, kind: str = "") -> dict:
        """Inventory of variant sets: counts, current winners, homes."""
        return curate.list_sets(project, kind=kind or None)

    @mcp.tool()
    def gf_materialize_winners(project: str) -> dict:
        """Rebuild the winners/ projection folder from the manifest + history."""
        return curate.materialize_winners(project)

    @mcp.tool()
    def gf_discard(project: str, image_path: str) -> dict:
        """Soft-delete a media file into _TO_PURGE (verified copy; never hard-delete)."""
        return curate.discard(project, image_path)

    @mcp.tool()
    def gf_adopt_set(project: str, set_id: str, dir: str) -> dict:
        """Register an existing folder as a set's history (no files are moved)."""
        return curate.adopt_set(project, set_id, dir)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_mcp.py -v`
Expected: PASS (all, including the new registration test)

- [ ] **Step 5: Commit**

```bash
cd R:/Dev/tools/content-factory
git add gf/mcp_server.py tests/test_mcp.py
git commit -m "feat: register six curation MCP tools on generation-factory"
```

---

### Task 8: CLI mirrors + docs

**Files:**
- Modify: `gf/cli.py` (append commands)
- Modify: `docs/ЗАДАЧНИК.md` (Ф2a status)
- Test: `tests/test_cli.py` (extend help test)

**Interfaces:**
- Consumes: `gf.curate`.
- Produces: CLI commands `add-variant`, `set-winner`, `list-sets`, `materialize-winners`, `discard`, `adopt-set` printing JSON (`ensure_ascii=False, indent=2`).

- [ ] **Step 1: Extend the help test** — in `tests/test_cli.py`, add:

```python
def test_help_lists_curation_commands():
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    for c in ["add-variant", "set-winner", "list-sets",
              "materialize-winners", "discard", "adopt-set"]:
        assert c in r.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_cli.py -v`
Expected: FAIL — new command names not in help output

- [ ] **Step 3: Append to `gf/cli.py`** (after the existing commands, before `main()`):

```python
def _echo(result: dict) -> None:
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("add-variant")
def add_variant_cmd(project: str, image_path: str, set_id: str,
                    note: str = typer.Option("", help="комментарий-провенанс"),
                    date: str = typer.Option("", help="YYYY-MM-DD (lineart/final)"),
                    stage: str = typer.Option("", help="стем итерации, напр. magnific")):
    """Скопировать вариант в набор под каноничным именем (источник не трогается)."""
    from .curate import add_variant
    _echo(add_variant(project, image_path, set_id, note=note,
                      date=date or None, stage=stage or None))


@app.command("set-winner")
def set_winner_cmd(project: str, set_id: str, image_path: str):
    """Переставить winner-указатель набора (пиксели не двигаются)."""
    from .curate import set_winner
    _echo(set_winner(project, set_id, image_path))


@app.command("list-sets")
def list_sets_cmd(project: str, kind: str = typer.Option("", help="фильтр по kind")):
    """Инвентарь наборов: варианты, winner'ы."""
    from .curate import list_sets
    _echo(list_sets(project, kind=kind or None))


@app.command("materialize-winners")
def materialize_winners_cmd(project: str):
    """Пересобрать папку winners/ из манифеста и истории."""
    from .curate import materialize_winners
    _echo(materialize_winners(project))


@app.command("discard")
def discard_cmd(project: str, image_path: str):
    """Мягкое удаление в _TO_PURGE (hard-delete не существует)."""
    from .curate import discard
    _echo(discard(project, image_path))


@app.command("adopt-set")
def adopt_set_cmd(project: str, set_id: str, dir: str):
    """Зарегистрировать существующую папку как историю набора (без перемещений)."""
    from .curate import adopt_set
    _echo(adopt_set(project, set_id, dir))
```

- [ ] **Step 4: Run the CLI tests, then the full suite**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_cli.py -v && python -m pytest`
Expected: CLI tests pass; full suite green, live test skipped. Report actual counts.

- [ ] **Step 5: Update `docs/ЗАДАЧНИК.md`** — in section «Фаза 2 — Building-blocks», replace the two first bullets (`gf_save_asset`, `gf_assemble_shot`) with:

```markdown
- ✅ **Ф2a (курация) РЕАЛИЗОВАНА** — наборы вариантов + подвижный winner: `gf_add_variant`, `gf_set_winner`, `gf_list_sets`, `gf_materialize_winners`, `gf_discard`, `gf_adopt_set` (спека `superpowers/specs/2026-07-05-media-curation-routing-design.md`; `gf_save_asset` заменён этой парой инструментов).
- ⬜ Ф2b: `gf_contact_sheet` (PIL-монтаж winner'ов; добавит Pillow).
- ⬜ `gf_assemble_shot(project, shot, ...)` — генеративная сборка кадра из winner'ов кирпичей (lineart+cast+look+brand); частично упирается в Nano/Gemini-блокер.
```

- [ ] **Step 6: Commit**

```bash
cd R:/Dev/tools/content-factory
git add gf/cli.py tests/test_cli.py docs/ЗАДАЧНИК.md
git commit -m "feat: CLI mirrors for curation ops + задачник Ф2a"
```

---

## Ф2a Done — Definition

- Six curation tools registered on `generation-factory`; CLI mirrors work.
- Full unit suite green; all six safety invariants covered by tests: verified copy (hash-mismatch keeps source), no history overwrites (unique suffix), atomic manifest, soft-delete only, traversal guard, dangling-winner detection.
- Not in Ф2a (explicitly): `gf_contact_sheet` (Ф2b, Pillow), `gf_assemble_shot` (generative, later), Hermes wiring (Ф4), adoption run over the real Ряба project (manual, after Ф4 or via CLI when the user asks).
