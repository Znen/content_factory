# Contact Sheet (Ф2b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `gf_contact_sheet` — PIL-монтаж текущих winner'ов указанных наборов в один файл со стабильным именем `contact-sheets/<sheet_id>.png` (+ опциональный снапшот «как отправили» в `exports/`).

**Architecture:** One new module `gf/sheet.py` with a pure function `contact_sheet(project, sheet_id, set_ids, ...) -> dict` that reads the winners manifest, loads each winner image, lays them out in a grid with set_id labels, and writes the sheet. The sheet is a **projection** (like `winners/`): stable name, regeneration replaces the file — this is the ONE class of file the system may overwrite. Wired as MCP tool + CLI command, mirroring the six curation ops.

**Tech Stack:** Python ≥3.10, Pillow (NEW dependency, `pillow>=10`), existing `gf.curate_state` (manifest) + `gf.naming` (validation charset). Spec: `docs/superpowers/specs/2026-07-05-media-curation-routing-design.md` (`gf_contact_sheet` row + «Карта зон»: contact-sheets/ стабильные имена, снапшоты в exports/).

## Global Constraints

- **Projection semantics:** `media/contact-sheets/<sheet_id>.png` MAY be overwritten on regeneration (spec: «перегенерация заменяет»). Nothing else is ever overwritten; history (`generated/`, `references/`) is read-only here.
- **Snapshot:** `snapshot=True` → additionally copy the sheet to `media/exports/<sheet_id>-<YYYYMMDD-HHMMSSZ>.png` (UTC timestamp; exports are never overwritten — timestamped names).
- **Inputs:** winners only — for each `set_id`, resolve `manifest["winners"][set_id]["path"]` relative to `media/`. Sets with no winner or a dangling winner path go into `"skipped"` (with reason); the sheet renders from the rest. ZERO renderable winners → `{"error", "hint"}` dict, no file written.
- **sheet_id charset** = set-name charset `^[a-z0-9][a-z0-9._-]*$` (reuse `naming._NAME_RE`) — traversal-safe output name.
- **Errors are structured dicts** `{"error": str, "hint": str?}` — no raw exceptions across the MCP boundary (incl. contained `OSError` on write and unreadable/corrupt winner images → that set goes to `skipped`).
- **Grid:** `columns` param (default 4), cell 512×512 (thumbnail preserves aspect, centered on white), label strip under each cell with the `set_id` (PIL default font, black on white). Row count = ceil(n/columns).
- **No ledger record** — the sheet is a projection, not curated state (spec's ledger op list stays as-is).
- New dependency `pillow>=10` added to `pyproject.toml` `[project] dependencies` and installed via `python -m pip install -e ".[dev]"`.
- Windows, `python -m pytest`; suite currently 81 passed / 1 skipped — must stay green.

---

## File Structure

```
gf/
├── sheet.py           NEW — contact_sheet() (grid montage of winners)
├── mcp_server.py      MODIFY — register gf_contact_sheet in build_server()
└── cli.py             MODIFY — `contact-sheet` command
pyproject.toml         MODIFY — add pillow>=10
tests/
├── test_sheet.py      NEW
├── test_mcp.py        MODIFY — registration assert
└── test_cli.py        MODIFY — help assert
docs/ЗАДАЧНИК.md       MODIFY — Ф2b ✅
```

---

### Task 1: `gf/sheet.py` + Pillow dependency

**Files:**
- Modify: `pyproject.toml` (dependencies)
- Create: `gf/sheet.py`
- Test: `tests/test_sheet.py`

**Interfaces:**
- Consumes: `gf.curate_state.load_manifest/media_root/CurateStateError`, `gf.naming._NAME_RE` (via a small public re-export added here — see code: we match with our own compiled copy to avoid private import), Pillow.
- Produces (Task 2 relies on): `gf.sheet.contact_sheet(project: str, sheet_id: str, set_ids: list, columns: int = 4, snapshot: bool = False) -> dict` — success `{"sheet": "contact-sheets/<id>.png", "count": int, "skipped": [{"set_id","reason"},...]}` (+ `"snapshot": "exports/<id>-<ts>.png"` when requested); failure `{"error","hint"?}`.

- [ ] **Step 1: Add Pillow to `pyproject.toml`** — in `[project] dependencies`, after `"python-dotenv>=1.0",` add:

```toml
  "pillow>=10",
```

Then install: `cd R:/Dev/tools/content-factory && python -m pip install -e ".[dev]" --quiet && python -c "import PIL; print(PIL.__version__)"`
Expected: prints a version ≥10.

- [ ] **Step 2: Write the failing test** `tests/test_sheet.py`

```python
from pathlib import Path
import pytest
from PIL import Image
from gf import curate
from gf.sheet import contact_sheet

CELL, LABEL_H = 512, 28


def _proj(tmp_path):
    (tmp_path / "media").mkdir(exist_ok=True)
    return tmp_path


def _png(dir_: Path, name: str, size=(64, 48), color=(200, 30, 30)):
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / name
    Image.new("RGB", size, color).save(p)
    return p


def _make_winner(proj, set_id, name="v.png", size=(64, 48)):
    src = _png(proj / "incoming", name, size=size)
    added = curate.add_variant(str(proj), str(src), set_id)
    curate.set_winner(str(proj), set_id, added["path"])


def test_sheet_renders_grid_of_winners(tmp_path):
    proj = _proj(tmp_path)
    for i in range(1, 6):  # 5 winners → grid 4 колонки × 2 ряда
        _make_winner(proj, f"cast/actor{i}", f"a{i}.png")
    out = contact_sheet(str(proj), "test-sheet",
                        [f"cast/actor{i}" for i in range(1, 6)])
    assert "error" not in out
    assert out["count"] == 5 and out["skipped"] == []
    sheet = proj / "media" / out["sheet"]
    assert out["sheet"] == "contact-sheets/test-sheet.png"
    img = Image.open(sheet)
    assert img.size == (4 * CELL, 2 * (CELL + LABEL_H))


def test_sheet_skips_missing_and_dangling_winners(tmp_path):
    proj = _proj(tmp_path)
    _make_winner(proj, "cast/anna")
    _make_winner(proj, "cast/boris")
    # boris: сделать winner повисшим (удаляем файл истории напрямую — имитация внешней потери)
    from gf.curate_state import load_manifest
    m = load_manifest(proj)
    (proj / "media" / m["winners"]["cast/boris"]["path"]).unlink()
    out = contact_sheet(str(proj), "s",
                        ["cast/anna", "cast/boris", "cast/nobody"])
    assert out["count"] == 1
    reasons = {s["set_id"]: s["reason"] for s in out["skipped"]}
    assert "cast/nobody" in reasons and "cast/boris" in reasons


def test_sheet_zero_renderable_is_error(tmp_path):
    proj = _proj(tmp_path)
    out = contact_sheet(str(proj), "s", ["cast/nobody"])
    assert "error" in out
    assert not (proj / "media" / "contact-sheets").exists()


def test_sheet_regeneration_replaces_stable_name(tmp_path):
    proj = _proj(tmp_path)
    _make_winner(proj, "cast/anna", size=(64, 48))
    out1 = contact_sheet(str(proj), "s", ["cast/anna"])
    first_bytes = (proj / "media" / out1["sheet"]).read_bytes()
    _make_winner(proj, "cast/zoya", size=(48, 64))
    out2 = contact_sheet(str(proj), "s", ["cast/anna", "cast/zoya"])
    assert out2["sheet"] == out1["sheet"]  # стабильное имя
    assert (proj / "media" / out2["sheet"]).read_bytes() != first_bytes


def test_sheet_snapshot_goes_to_exports(tmp_path):
    proj = _proj(tmp_path)
    _make_winner(proj, "cast/anna")
    out = contact_sheet(str(proj), "s", ["cast/anna"], snapshot=True)
    snap = proj / "media" / out["snapshot"]
    assert out["snapshot"].startswith("exports/s-")
    assert snap.exists()
    assert snap.read_bytes() == (proj / "media" / out["sheet"]).read_bytes()


def test_sheet_rejects_bad_sheet_id(tmp_path):
    proj = _proj(tmp_path)
    _make_winner(proj, "cast/anna")
    for bad in ("../evil", "UPPER", "a/b", ""):
        assert "error" in contact_sheet(str(proj), bad, ["cast/anna"])


def test_sheet_unreadable_image_skipped(tmp_path):
    proj = _proj(tmp_path)
    _make_winner(proj, "cast/anna")
    # битый winner: валидный указатель на невалидный PNG
    src = _png(proj / "incoming", "junk.png")
    added = curate.add_variant(str(proj), str(src), "cast/junk")
    (proj / "media" / added["path"]).write_bytes(b"not a png at all")
    curate.set_winner(str(proj), "cast/junk", added["path"])
    out = contact_sheet(str(proj), "s", ["cast/anna", "cast/junk"])
    assert out["count"] == 1
    assert out["skipped"][0]["set_id"] == "cast/junk"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_sheet.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gf.sheet'`

- [ ] **Step 4: Write `gf/sheet.py`**

```python
"""Contact sheet — grid montage of current winners into a stable-named projection.

media/contact-sheets/<sheet_id>.png is a PROJECTION: regeneration replaces it
(the only overwrite class in the system, per the design spec). Snapshots «как
отправили клиенту» go to media/exports/ with timestamped, never-overwritten names.
Reads history and the winners manifest; never writes to history.
"""

from __future__ import annotations

import math
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .curate_state import CurateStateError, load_manifest, media_root

CELL = 512          # квадратная ячейка миниатюры
LABEL_H = 28        # полоса подписи под ячейкой
SHEETS_DIR = "contact-sheets"
EXPORTS_DIR = "exports"

_SHEET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _err(error: str, hint: str = "") -> dict:
    out = {"error": error}
    if hint:
        out["hint"] = hint
    return out


def contact_sheet(project: str, sheet_id: str, set_ids: list,
                  columns: int = 4, snapshot: bool = False) -> dict:
    """Montage current winners of `set_ids` into contact-sheets/<sheet_id>.png."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return _err("Pillow is not installed", "python -m pip install pillow")

    if not isinstance(sheet_id, str) or not _SHEET_ID_RE.match(sheet_id or ""):
        return _err(f"invalid sheet_id {sheet_id!r} (lowercase letters/digits/._- )")
    if not set_ids:
        return _err("set_ids is empty", "pass the sets whose winners to montage")
    columns = max(1, int(columns))

    project_dir = Path(project)
    media = media_root(project_dir)
    try:
        manifest = load_manifest(project_dir)
    except CurateStateError as e:
        return _err(str(e))

    tiles, skipped = [], []
    for set_id in set_ids:
        entry = manifest["winners"].get(set_id)
        if not entry:
            skipped.append({"set_id": set_id, "reason": "no winner set"})
            continue
        src = media / entry.get("path", "")
        if not src.is_file():
            skipped.append({"set_id": set_id, "reason": "winner file missing (dangling)"})
            continue
        try:
            img = Image.open(src)
            img.load()
        except OSError:
            skipped.append({"set_id": set_id, "reason": "unreadable image"})
            continue
        tiles.append((set_id, img.convert("RGB")))

    if not tiles:
        return _err("no renderable winners among the given set_ids",
                    "set winners first (gf_set_winner) or check gf_list_sets")

    rows = math.ceil(len(tiles) / columns)
    sheet = Image.new("RGB", (columns * CELL, rows * (CELL + LABEL_H)), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for i, (set_id, img) in enumerate(tiles):
        col, row = i % columns, i // columns
        x0, y0 = col * CELL, row * (CELL + LABEL_H)
        thumb = img.copy()
        thumb.thumbnail((CELL, CELL))
        sheet.paste(thumb, (x0 + (CELL - thumb.width) // 2,
                            y0 + (CELL - thumb.height) // 2))
        draw.text((x0 + 6, y0 + CELL + 6), set_id, fill="black", font=font)

    out_dir = media / SHEETS_DIR
    out_path = out_dir / f"{sheet_id}.png"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        sheet.save(out_path)  # проекция: стабильное имя, замена разрешена
    except OSError as e:
        return _err(f"failed to write sheet: {e}", "check disk space/permissions")

    result = {"sheet": f"{SHEETS_DIR}/{sheet_id}.png", "count": len(tiles),
              "skipped": skipped}
    if snapshot:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
        snap = media / EXPORTS_DIR / f"{sheet_id}-{ts}.png"
        try:
            snap.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(out_path, snap)
            result["snapshot"] = f"{EXPORTS_DIR}/{snap.name}"
        except OSError as e:
            result["snapshot_error"] = f"snapshot failed: {e}"
    return result
```

- [ ] **Step 5: Run tests to verify they pass, then full suite**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_sheet.py -v && python -m pytest`
Expected: test_sheet 7 passed; full suite ~88 passed / 1 skipped (report ACTUAL counts, do not force).

- [ ] **Step 6: Commit**

```bash
cd R:/Dev/tools/content-factory
git add pyproject.toml gf/sheet.py tests/test_sheet.py
git commit -m "feat: contact_sheet — grid montage of winners (Pillow), stable-name projection"
```

---

### Task 2: MCP tool + CLI + docs

**Files:**
- Modify: `gf/mcp_server.py` (inside `build_server()`, after `gf_adopt_set`, before `return mcp, settings`)
- Modify: `gf/cli.py` (after `adopt-set` command, before `main()`)
- Modify: `docs/ЗАДАЧНИК.md`
- Test: `tests/test_mcp.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `gf.sheet.contact_sheet(project, sheet_id, set_ids, columns=4, snapshot=False) -> dict` (Task 1).
- Produces: MCP tool `gf_contact_sheet`; CLI command `contact-sheet`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_mcp.py`:

```python
def test_contact_sheet_tool_registered():
    import asyncio
    from gf.mcp_server import build_server
    mcp, _ = build_server()
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert "gf_contact_sheet" in names
```

and to `tests/test_cli.py`:

```python
def test_help_lists_contact_sheet():
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0 and "contact-sheet" in r.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_mcp.py::test_contact_sheet_tool_registered tests/test_cli.py::test_help_lists_contact_sheet -v`
Expected: both FAIL (tool/command not registered yet)

- [ ] **Step 3: Register the MCP tool** — in `gf/mcp_server.py`, inside `build_server()`, after the `gf_adopt_set` tool and before `return mcp, settings`, add:

```python
    @mcp.tool()
    def gf_contact_sheet(project: str, sheet_id: str, set_ids: list,
                         columns: int = 4, snapshot: bool = False) -> dict:
        """Montage current winners into contact-sheets/<sheet_id>.png (stable name,
        regeneration replaces). snapshot=True also copies to exports/ (timestamped)."""
        from .sheet import contact_sheet
        return contact_sheet(project, sheet_id, set_ids, columns=columns,
                             snapshot=snapshot)
```

- [ ] **Step 4: Add the CLI command** — in `gf/cli.py`, after the `adopt-set` command and before `def main():`, add:

```python
@app.command("contact-sheet")
def contact_sheet_cmd(project: str, sheet_id: str,
                      set_ids: List[str] = typer.Argument(..., help="set_id...(winner'ы)"),
                      columns: int = typer.Option(4, help="колонок в сетке"),
                      snapshot: bool = typer.Option(False, help="снапшот в exports/")):
    """Смонтировать winner'ы наборов в контакт-лист (стабильное имя)."""
    from .sheet import contact_sheet
    _echo(contact_sheet(project, sheet_id, set_ids, columns=columns,
                        snapshot=snapshot))
```

(`List` уже импортирован в `gf/cli.py` из `typing` — проверить и не дублировать.)

- [ ] **Step 5: Run tests, then full suite**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_mcp.py tests/test_cli.py -v && python -m pytest`
Expected: registration+help tests pass; full suite green (report ACTUAL counts).

- [ ] **Step 6: Update `docs/ЗАДАЧНИК.md`** — replace the line
`- ⬜ Ф2b: `gf_contact_sheet` (PIL-монтаж winner'ов; добавит Pillow).`
with:
`- ✅ **Ф2b: `gf_contact_sheet` РЕАЛИЗОВАН** — PIL-монтаж winner'ов → `contact-sheets/<sheet_id>.png` (стабильное имя, перегенерация заменяет; снапшоты в `exports/` с таймстампом; Pillow добавлен в зависимости).`
Also in section «Фаза 3 — Контакт-листы + память процесса» mark the first bullet: replace `- ⬜ `gf_contact_sheet`(project, selection)` — сборка по запросу (за дату / последние N / список). НЕ авто.` with `- ✅ `gf_contact_sheet` — реализован в Ф2b (вход — явный список set_ids, по запросу; НЕ авто).`

- [ ] **Step 7: Commit**

```bash
cd R:/Dev/tools/content-factory
git add gf/mcp_server.py gf/cli.py tests/test_mcp.py tests/test_cli.py docs/ЗАДАЧНИК.md
git commit -m "feat: gf_contact_sheet MCP tool + CLI + задачник Ф2b"
```

---

## Ф2b Done — Definition

- `gf_contact_sheet` зарегистрирован на `generation-factory` (станет 13-м инструментом у Hermes после рестарта гейтвея — НЕ рестартуем автоматически, зафиксировать как заметку).
- Суита зелёная; проекционная семантика покрыта тестами (stable name replace, skipped, zero→error, snapshot, битые изображения, traversal-safe sheet_id).
- Реальный smoke на Рябе (после исполнения плана, контроллером): `gf contact-sheet <ryaba> storyboard-lineart lineart/shot-01 … lineart/shot-08` → один PNG 4×2 из твоих winner-лайнартов.
```
