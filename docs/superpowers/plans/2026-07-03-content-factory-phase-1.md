# Content Factory — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a clean `content-factory` MCP server (`generation-factory`) exposing two generative tools to Hermes — `gf_generate_draft` (ComfyUI, cheap drafts) and `gf_generate_final` (Nano Banana, client-facing finals with multi-image refs) — with lean, decoupled cost-gating.

**Architecture:** Python package `gf`, structured one-to-one after `knowledge-factory` (`@dataclass` config → `build_core()` → `mcp_server` with 3 transports → Typer CLI → per-module tests). Backends are thin HTTP clients: `nano.py` (ported from the old agent, decoupled from `tools.common`) talks to the external Nitro Express server on `:3001`; `comfyui.py` (written from scratch — no Python client existed in the old agent) talks to ComfyUI on `:8188` via the standard `POST /prompt` → poll `/history` → `GET /view` REST flow. Cost-gating is a clean rewrite (`pricing.py` + `budget.py`) that logs to `media/.gf_cost_log.jsonl` with an optional env soft-cap — it does NOT carry over the old `brief.yaml`/`tools_registry.json`/`_REPO_ROOT` coupling.

**Tech Stack:** Python ≥3.10, `mcp>=1.2` (FastMCP via `mcp.server.fastmcp.FastMCP`), `typer>=0.12`, `requests>=2.32`, `python-dotenv>=1.0`, `pytest>=8.0`. setuptools build backend. No pydantic. No database stack (unlike kf).

## Global Constraints

- **Python floor:** `requires-python = ">=3.10"`. Local interpreter is 3.10.11.
- **Package name:** `gf`. CLI console-script: `gf`. Env prefix for own keys: `GF_`. MCP server display name: `generation-factory`. Tool prefix: `gf_`.
- **MCP port:** default `8766` (kf already owns `8765`). Bind default `127.0.0.1`. Token env: `GF_MCP_TOKEN` (empty/unset → `None`).
- **Bearer compare:** use `hmac.compare_digest`, never raw `!=` (fixing kf's known timing-unsafe compare).
- **Config style:** plain `@dataclass Settings` + `load_settings()` reading `os.environ` with in-code defaults; `load_dotenv()` wrapped in `try/except ImportError`. No pydantic `BaseSettings`.
- **Backends stay pure:** HTTP clients contain zero cost/budget/project-structure logic. Cost-gating happens in the MCP tool wrapper (`_*_impl`), never inside `nano.py`/`comfyui.py`.
- **Windows UTF-8:** `cli.main()` must reconfigure stdout/stderr to `utf-8, errors="replace"` before running the app (Cyrillic output on cp1251 consoles).
- **External services (this machine, verified 2026-07-03):** Nitro Express running on `http://localhost:3001` (password in `~/.lionfilms/nitro_banana.env` as `NITRO_BANANA_APP_PASSWORD`). ComfyUI installed at `Q:\ComfyUI_windows_portable` (default `http://127.0.0.1:8188`, NOT running by default — start before real ComfyUI smoke). Installed SDXL checkpoints include `juggernautxl_ragnarok.safetensors`, `realvisxl_v50.safetensors`, `sd_xl_base_1.0.safetensors`; FLUX `flux1-schnell-fp8.safetensors`.
- **No verbatim port of old `budget.py`/`pricing.py`/`workspace.py`/`base_gate.py`** — they are coupled to the discarded old structure. Port only the Nano HTTP logic.

---

## File Structure

```
content-factory/
├── pyproject.toml                       # setuptools, gf console-script, deps
├── .gitignore
├── .env.example
├── README.md
├── gf/
│   ├── __init__.py                      # __version__
│   ├── config.py                        # @dataclass Settings + load_settings()
│   ├── pricing.py                       # estimate(backend, n) -> usd  (clean, no registry)
│   ├── budget.py                        # cost log + optional soft cap, per-project
│   ├── media.py                         # project media path resolution (drafts/generated dirs)
│   ├── backends/
│   │   ├── __init__.py
│   │   ├── nano.py                       # Nano Banana HTTP client (ported, decoupled)
│   │   └── comfyui.py                    # ComfyUI REST client (new)
│   ├── workflows/
│   │   └── sdxl_txt2img_api.json         # API-format template, parameterized
│   ├── core.py                          # build_core(settings) -> shared handles
│   ├── mcp_server.py                    # _*_impl, build_server, run_server (3 transports)
│   └── cli.py                           # Typer app + main()
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── test_pricing.py
    ├── test_budget.py
    ├── test_media.py
    ├── test_nano.py
    ├── test_comfyui.py
    ├── test_mcp.py
    └── test_cli.py
```

Responsibilities:
- `config.py` — all env → `Settings`. Single source of defaults.
- `pricing.py` — pure cost estimate, no I/O, no project structure.
- `budget.py` — append cost records to `<project>/media/.gf_cost_log.jsonl`, sum spend, enforce optional cap. Owns the cost-log format.
- `media.py` — resolves media subfolders for a project (drafts, dated `generated/<date>/`); creates dirs. Owns the on-disk layout from the storage spec.
- `backends/nano.py` — login/token-cache/encode/call/save for the Nitro Express server. Pure HTTP.
- `backends/comfyui.py` — submit workflow, poll history, download images. Pure HTTP.
- `core.py` — `build_core(settings)` returns the handles the tools need (a small dataclass); reused by both `cli` and `mcp_server` (avoids kf's `_core`/`build_server` duplication).
- `mcp_server.py` — pure `_*_impl` functions (unit-testable with fake backends) + `build_server()` wrapping them in `@mcp.tool()` + `run_server(http)` with the 3-transport pattern.
- `cli.py` — `serve`, `generate-draft`, `generate-final`, `version` commands + UTF-8 `main()`.

---

### Task 1: Project skeleton, config, git

**Files:**
- Create: `R:/Dev/tools/content-factory/pyproject.toml`
- Create: `R:/Dev/tools/content-factory/.gitignore`
- Create: `R:/Dev/tools/content-factory/.env.example`
- Create: `R:/Dev/tools/content-factory/gf/__init__.py`
- Create: `R:/Dev/tools/content-factory/gf/config.py`
- Create: `R:/Dev/tools/content-factory/gf/backends/__init__.py`
- Create: `R:/Dev/tools/content-factory/tests/test_config.py`

**Interfaces:**
- Produces: `gf.config.Settings` (frozen-ish dataclass) with fields listed below; `gf.config.load_settings() -> Settings`.

`Settings` fields (exact names/types — later tasks depend on these):
```
comfyui_url: str
comfyui_ckpt: str
comfyui_workflow: str          # path to API-format workflow json ("" = use bundled default)
nano_server_url: str
nano_env_file: str             # path to nitro env with the app password ("" = default ~/.lionfilms)
nano_timeout: int
image_cap_usd: float | None    # None = no cap
mcp_bind: str
mcp_port: int
mcp_token: str | None
```

- [ ] **Step 1: Create `.gitignore` and `.env.example` first** (so secrets never get committed)

`.gitignore`:
```gitignore
.env
.venv/
__pycache__/
*.pyc
.pytest_cache/
.superpowers/
*.egg-info/
/media/
```

`.env.example`:
```dotenv
PROJECT_NAME=content-factory

# ComfyUI (drafts)
GF_COMFYUI_URL=http://127.0.0.1:8188
GF_COMFYUI_CKPT=juggernautxl_ragnarok.safetensors
GF_COMFYUI_WORKFLOW=

# Nano Banana (finals) — external Nitro Express server
GF_NANO_SERVER_URL=http://localhost:3001
GF_NANO_ENV_FILE=
GF_NANO_TIMEOUT=120

# Cost-gating (soft cap; leave blank for no cap)
GF_IMAGE_CAP_USD=

# MCP Gateway
GF_MCP_BIND=127.0.0.1
GF_MCP_PORT=8766
GF_MCP_TOKEN=
```

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[project]
name = "content-factory"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
  "mcp>=1.2",
  "typer>=0.12",
  "requests>=2.32",
  "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
gf = "gf.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["gf*"]

[tool.setuptools.package-data]
gf = ["workflows/*.json"]

[tool.pytest.ini_options]
markers = ["live: hits a real external service (ComfyUI/Nitro); skipped by default"]
```

- [ ] **Step 3: Create package init files**

`gf/__init__.py`:
```python
__version__ = "0.1.0"
```

`gf/backends/__init__.py`:
```python
```
(empty file)

- [ ] **Step 4: Write the failing test** `tests/test_config.py`

```python
from gf.config import load_settings


def test_defaults(monkeypatch):
    for k in list(__import__("os").environ):
        if k.startswith("GF_"):
            monkeypatch.delenv(k, raising=False)
    s = load_settings()
    assert s.comfyui_url == "http://127.0.0.1:8188"
    assert s.comfyui_ckpt.endswith(".safetensors")
    assert s.nano_server_url == "http://localhost:3001"
    assert s.nano_timeout == 120
    assert s.image_cap_usd is None
    assert s.mcp_bind == "127.0.0.1"
    assert s.mcp_port == 8766
    assert s.mcp_token is None


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("GF_MCP_PORT", "9000")
    monkeypatch.setenv("GF_MCP_TOKEN", "secret")
    monkeypatch.setenv("GF_IMAGE_CAP_USD", "5.5")
    s = load_settings()
    assert s.mcp_port == 9000
    assert s.mcp_token == "secret"
    assert s.image_cap_usd == 5.5
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gf.config'`

- [ ] **Step 6: Write `gf/config.py`**

```python
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    comfyui_url: str
    comfyui_ckpt: str
    comfyui_workflow: str
    nano_server_url: str
    nano_env_file: str
    nano_timeout: int
    image_cap_usd: "float | None"
    mcp_bind: str
    mcp_port: int
    mcp_token: "str | None"


def _float_or_none(raw: str) -> "float | None":
    raw = (raw or "").strip()
    return float(raw) if raw else None


def load_settings() -> Settings:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    return Settings(
        comfyui_url=os.environ.get("GF_COMFYUI_URL", "http://127.0.0.1:8188"),
        comfyui_ckpt=os.environ.get("GF_COMFYUI_CKPT", "juggernautxl_ragnarok.safetensors"),
        comfyui_workflow=os.environ.get("GF_COMFYUI_WORKFLOW", ""),
        nano_server_url=os.environ.get("GF_NANO_SERVER_URL", "http://localhost:3001"),
        nano_env_file=os.environ.get("GF_NANO_ENV_FILE", ""),
        nano_timeout=int(os.environ.get("GF_NANO_TIMEOUT", "120")),
        image_cap_usd=_float_or_none(os.environ.get("GF_IMAGE_CAP_USD", "")),
        mcp_bind=os.environ.get("GF_MCP_BIND", "127.0.0.1"),
        mcp_port=int(os.environ.get("GF_MCP_PORT", "8766")),
        mcp_token=os.environ.get("GF_MCP_TOKEN") or None,
    )
```

- [ ] **Step 7: Install the package editable + run tests**

Run: `cd R:/Dev/tools/content-factory && python -m pip install -e ".[dev]" && python -m pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 8: git init and first commit**

```bash
cd R:/Dev/tools/content-factory
git init
git add pyproject.toml .gitignore .env.example gf tests docs
git commit -m "feat: content-factory skeleton + config"
```
(Note: `docs/` already contains the specs and this plan.)

---

### Task 2: Cost estimate (`pricing.py`)

**Files:**
- Create: `R:/Dev/tools/content-factory/gf/pricing.py`
- Test: `R:/Dev/tools/content-factory/tests/test_pricing.py`

**Interfaces:**
- Produces: `gf.pricing.estimate(backend: str, n: int = 1) -> float` — USD estimate. Text/local backends cost 0.

Cost model (clean, no registry file): flat per-image USD by backend. Nano ≈ $0.04/image (from old fallback table); ComfyUI local = $0.0.

- [ ] **Step 1: Write the failing test** `tests/test_pricing.py`

```python
import pytest
from gf.pricing import estimate


def test_nano_per_image():
    assert estimate("nano", 1) == pytest.approx(0.04)
    assert estimate("nano", 3) == pytest.approx(0.12)


def test_comfyui_is_free():
    assert estimate("comfyui", 4) == 0.0


def test_unknown_backend_is_free():
    assert estimate("something", 2) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_pricing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gf.pricing'`

- [ ] **Step 3: Write `gf/pricing.py`**

```python
"""Flat per-image cost estimate. Decoupled from any registry/project structure."""

_PER_IMAGE_USD = {
    "nano": 0.04,       # Nitro/Gemini image, from old fallback table
    "comfyui": 0.0,     # local GPU, no marginal cost
}


def estimate(backend: str, n: int = 1) -> float:
    """USD estimate for generating `n` images on `backend`. Unknown → free."""
    per = _PER_IMAGE_USD.get(backend, 0.0)
    return round(per * max(0, n), 4)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_pricing.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
cd R:/Dev/tools/content-factory
git add gf/pricing.py tests/test_pricing.py
git commit -m "feat: pricing.estimate — flat per-image cost"
```

---

### Task 3: Cost log + soft cap (`budget.py`)

**Files:**
- Create: `R:/Dev/tools/content-factory/gf/budget.py`
- Test: `R:/Dev/tools/content-factory/tests/test_budget.py`

**Interfaces:**
- Consumes: nothing from other modules (pure fs + json).
- Produces:
  - `gf.budget.log_cost(project_dir: Path, backend: str, n: int, cost_usd: float, note: str = "") -> None` — appends one JSON line to `<project_dir>/media/.gf_cost_log.jsonl`.
  - `gf.budget.spent(project_dir: Path) -> float` — sum of `cost_usd` in the log (0.0 if none).
  - `gf.budget.check(project_dir: Path, add_usd: float, cap_usd: "float | None") -> dict` — returns `{"allowed": bool, "spent": float, "cap": float | None, "reason": str}`. `cap_usd is None` → always allowed.

Cost-log line format: `{"ts": <unix float>, "backend": str, "n": int, "cost_usd": float, "note": str}`.

- [ ] **Step 1: Write the failing test** `tests/test_budget.py`

```python
from pathlib import Path
from gf.budget import log_cost, spent, check


def test_spent_empty(tmp_path):
    assert spent(tmp_path) == 0.0


def test_log_and_sum(tmp_path):
    log_cost(tmp_path, "nano", 2, 0.08, note="shot-01")
    log_cost(tmp_path, "nano", 1, 0.04)
    assert round(spent(tmp_path), 4) == 0.12
    logfile = tmp_path / "media" / ".gf_cost_log.jsonl"
    assert logfile.exists()
    assert len(logfile.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_check_no_cap_allows(tmp_path):
    out = check(tmp_path, 100.0, None)
    assert out["allowed"] is True
    assert out["cap"] is None


def test_check_cap_blocks_over(tmp_path):
    log_cost(tmp_path, "nano", 1, 4.0)
    out = check(tmp_path, 1.5, cap_usd=5.0)
    assert out["allowed"] is False
    assert out["spent"] == 4.0
    assert "cap" in out["reason"].lower()


def test_check_cap_allows_under(tmp_path):
    log_cost(tmp_path, "nano", 1, 1.0)
    out = check(tmp_path, 1.0, cap_usd=5.0)
    assert out["allowed"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_budget.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gf.budget'`

- [ ] **Step 3: Write `gf/budget.py`**

```python
"""Per-project cost log + optional soft cap. Owns the cost-log file format.

Decoupled from the old agent: no brief.yaml, no tools_registry, no _REPO_ROOT.
The log lives next to the project's media at <project>/media/.gf_cost_log.jsonl.
"""

import json
import time
from pathlib import Path

_LOG_NAME = ".gf_cost_log.jsonl"


def _log_path(project_dir: Path) -> Path:
    return Path(project_dir) / "media" / _LOG_NAME


def log_cost(project_dir: Path, backend: str, n: int, cost_usd: float, note: str = "") -> None:
    path = _log_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": time.time(), "backend": backend, "n": n,
              "cost_usd": round(float(cost_usd), 4), "note": note}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def spent(project_dir: Path) -> float:
    path = _log_path(project_dir)
    if not path.exists():
        return 0.0
    total = 0.0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            total += float(json.loads(line).get("cost_usd", 0.0))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return round(total, 4)


def check(project_dir: Path, add_usd: float, cap_usd: "float | None") -> dict:
    already = spent(project_dir)
    if cap_usd is None:
        return {"allowed": True, "spent": already, "cap": None, "reason": "no cap"}
    allowed = (already + add_usd) <= cap_usd
    reason = "ok" if allowed else (
        f"would exceed image cap ${cap_usd:.2f} (spent ${already:.2f} + ${add_usd:.2f})")
    return {"allowed": allowed, "spent": already, "cap": cap_usd, "reason": reason}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_budget.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
cd R:/Dev/tools/content-factory
git add gf/budget.py tests/test_budget.py
git commit -m "feat: budget cost-log + optional soft cap"
```

---

### Task 4: Media path resolution (`media.py`)

**Files:**
- Create: `R:/Dev/tools/content-factory/gf/media.py`
- Test: `R:/Dev/tools/content-factory/tests/test_media.py`

**Interfaces:**
- Produces:
  - `gf.media.drafts_dir(project_dir: Path, date: str) -> Path` → `<project>/media/generated/<date>/_drafts/` (created).
  - `gf.media.shot_dir(project_dir: Path, date: str, shot: str) -> Path` → `<project>/media/generated/<date>/<shot>/` (created).
  - `gf.media.next_index(directory: Path, prefix: str, ext: str = ".png") -> int` → next 1-based counter for files named `<prefix>-NN<ext>`.
  - `gf.media.today() -> str` → `YYYY-MM-DD` (callers pass an explicit date normally; this is the default helper).

Layout is from the storage spec: `media/generated/<YYYY-MM-DD>/`. Drafts go to a `_drafts/` subfolder; assembled shots to `shot-XX/` (shot dir used in Phase 2, added here so the module is complete).

- [ ] **Step 1: Write the failing test** `tests/test_media.py`

```python
from gf.media import drafts_dir, shot_dir, next_index, today


def test_drafts_dir_created(tmp_path):
    d = drafts_dir(tmp_path, "2026-07-03")
    assert d.exists()
    assert d.as_posix().endswith("media/generated/2026-07-03/_drafts")


def test_shot_dir_created(tmp_path):
    d = shot_dir(tmp_path, "2026-07-03", "shot-01")
    assert d.exists()
    assert d.as_posix().endswith("media/generated/2026-07-03/shot-01")


def test_next_index_counts(tmp_path):
    assert next_index(tmp_path, "draft") == 1
    (tmp_path / "draft-01.png").write_bytes(b"x")
    (tmp_path / "draft-02.png").write_bytes(b"x")
    assert next_index(tmp_path, "draft") == 3


def test_today_format():
    s = today()
    assert len(s) == 10 and s[4] == "-" and s[7] == "-"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_media.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gf.media'`

- [ ] **Step 3: Write `gf/media.py`**

```python
"""Project media layout from the storage spec: media/generated/<date>/…"""

import datetime as dt
import re
from pathlib import Path


def today() -> str:
    return dt.date.today().isoformat()


def _generated(project_dir: Path, date: str) -> Path:
    return Path(project_dir) / "media" / "generated" / date


def drafts_dir(project_dir: Path, date: str) -> Path:
    d = _generated(project_dir, date) / "_drafts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def shot_dir(project_dir: Path, date: str, shot: str) -> Path:
    d = _generated(project_dir, date) / shot
    d.mkdir(parents=True, exist_ok=True)
    return d


def next_index(directory: Path, prefix: str, ext: str = ".png") -> int:
    directory = Path(directory)
    if not directory.exists():
        return 1
    pat = re.compile(rf"^{re.escape(prefix)}-(\d+){re.escape(ext)}$")
    highest = 0
    for p in directory.iterdir():
        m = pat.match(p.name)
        if m:
            highest = max(highest, int(m.group(1)))
    return highest + 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_media.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
cd R:/Dev/tools/content-factory
git add gf/media.py tests/test_media.py
git commit -m "feat: media path resolution (generated/<date>)"
```

---

### Task 5: Nano Banana backend (`backends/nano.py`)

**Files:**
- Create: `R:/Dev/tools/content-factory/gf/backends/nano.py`
- Test: `R:/Dev/tools/content-factory/tests/test_nano.py`
- Reference (read, do not import): `Q:/Lion Films. AI studio/tools/nitro_banana/nitro_generate.py`

**Interfaces:**
- Consumes: nothing from other `gf` modules (pure HTTP client — keeps backend pure).
- Produces:
  - `gf.backends.nano.NanoError(Exception)`
  - `gf.backends.nano.generate(prompt: str, refs: list[Path], out_dir: Path, *, server_url: str, password: str | None, timeout: int = 120, aspect: str = "9:16", token_cache: Path | None = None, session=None) -> list[Path]` — logs in (or uses cached token), edits with up to 4 base64 refs, saves the returned image(s), returns saved paths.
  - Helper (tested directly): `gf.backends.nano.encode_inputs(paths: list[Path]) -> tuple[list[str], list[str]]`.
  - Helper (tested directly): `gf.backends.nano.save_image(image_url_data: str, out_path: Path) -> int`.

Design notes (decoupling from the old file): drop the module-level `from tools.common import …` and all `_enforce_budget`/`workspace` logic — cost-gating now lives in the tool wrapper. Keep `login`/token-cache/`call_gemini`/`encode_inputs`/`save_image` logic verbatim in behavior. `session` param (defaults to `requests`) lets tests inject a fake without a live server. No seed param (Nano doesn't support it). Max 4 refs (raise `NanoError` beyond).

- [ ] **Step 1: Write the failing test** `tests/test_nano.py`

```python
import base64
import json
from pathlib import Path
import pytest
from gf.backends import nano


def _png(tmp_path, name):
    p = tmp_path / name
    p.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
    return p


def test_encode_inputs_base64_and_mime(tmp_path):
    p = _png(tmp_path, "ref.png")
    b64s, mimes = nano.encode_inputs([p])
    assert mimes == ["image/png"]
    assert base64.b64decode(b64s[0]) == b"\x89PNG\r\n\x1a\nFAKE"


def test_encode_rejects_unsupported(tmp_path):
    bad = tmp_path / "x.gif"
    bad.write_bytes(b"GIF")
    with pytest.raises(ValueError):
        nano.encode_inputs([bad])


def test_save_image_data_uri(tmp_path):
    raw = b"hello-png-bytes"
    data_uri = "data:image/png;base64," + base64.b64encode(raw).decode()
    out = tmp_path / "o.png"
    n = nano.save_image(data_uri, out)
    assert out.read_bytes() == raw and n == len(raw)


class _FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeSession:
    """Minimal requests-like stub: login then /api/gemini."""
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/api/auth/login"):
            return _FakeResp(200, {"token": "tok-123"})
        if url.endswith("/api/gemini"):
            raw = base64.b64encode(b"final-image").decode()
            return _FakeResp(200, {"imageUrl": "data:image/png;base64," + raw})
        return _FakeResp(404, {"error": "nope"})


def test_generate_writes_final(tmp_path):
    ref = _png(tmp_path, "face.png")
    out_dir = tmp_path / "out"
    sess = _FakeSession()
    saved = nano.generate(
        "make it cinematic", [ref], out_dir,
        server_url="http://localhost:3001", password="pw",
        token_cache=tmp_path / "tok.json", session=sess,
    )
    assert len(saved) == 1 and saved[0].exists()
    assert saved[0].read_bytes() == b"final-image"
    # login happened + gemini payload carried base64 refs
    gemini_call = [c for c in sess.calls if c[0].endswith("/api/gemini")][0]
    body = gemini_call[1]["json"]
    assert body["action"] == "edit"
    assert len(body["base64Datas"]) == 1 and body["mimeTypes"] == ["image/png"]


def test_generate_rejects_more_than_4_refs(tmp_path):
    refs = [_png(tmp_path, f"r{i}.png") for i in range(5)]
    with pytest.raises(nano.NanoError):
        nano.generate("x", refs, tmp_path / "o",
                      server_url="http://localhost:3001", password="pw",
                      token_cache=tmp_path / "t.json", session=_FakeSession())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_nano.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gf.backends.nano'`

- [ ] **Step 3: Write `gf/backends/nano.py`**

```python
"""Nano Banana backend — thin HTTP client for the external Nitro Express server.

Ported from Q:/Lion Films. AI studio/tools/nitro_banana/nitro_generate.py, stripped
of all tools.common / budget / workspace coupling. Pure HTTP: cost-gating and project
layout live in the caller. No seed support (server doesn't accept one).
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import time
from pathlib import Path

import requests

DEFAULT_TIMEOUT = 120
TOKEN_TTL_S = 7 * 24 * 60 * 60
DEFAULT_TOKEN_CACHE = Path.home() / ".lionfilms" / "nitro_banana_token.json"
VALID_ASPECTS = {"16:9", "1:1", "3:4", "4:3", "9:16"}
MAX_REFS = 4
SUPPORTED_INPUT_MIMES = {
    ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".webp": "image/webp",
}


class NanoError(Exception):
    pass


class AuthExpired(Exception):
    pass


def encode_inputs(paths: list[Path]) -> tuple[list[str], list[str]]:
    b64s, mimes = [], []
    for p in paths:
        p = Path(p)
        if not p.exists():
            raise FileNotFoundError(f"Input file not found: {p}")
        mime = SUPPORTED_INPUT_MIMES.get(p.suffix.lower())
        if not mime:
            raise ValueError(
                f"Unsupported input type: {p.name} (supported: {sorted(SUPPORTED_INPUT_MIMES)})")
        b64s.append(base64.b64encode(p.read_bytes()).decode("ascii"))
        mimes.append(mime)
    return b64s, mimes


def save_image(image_url_data: str, out_path: Path) -> int:
    b64 = image_url_data.split(",", 1)[1] if image_url_data.startswith("data:") else image_url_data
    raw = base64.b64decode(b64)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw)
    return len(raw)


def _get_cached_token(cache_path: Path) -> "str | None":
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if data.get("expires_at", 0) > time.time() + 60:
            return data.get("token")
    except (json.JSONDecodeError, OSError):
        return None
    return None


def _cache_token(cache_path: Path, token: str) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"token": token, "expires_at": time.time() + TOKEN_TTL_S}),
        encoding="utf-8")


def _login(session, server_url: str, password: str) -> str:
    url = f"{server_url.rstrip('/')}/api/auth/login"
    try:
        r = session.post(url, json={"password": password}, timeout=10)
    except requests.exceptions.ConnectionError as e:
        raise NanoError(f"Cannot reach Nitro server at {server_url}. "
                        f"Start it: `cd R:\\nitro_banana && npm run dev:server`. ({e})") from e
    if r.status_code == 401:
        raise NanoError("Login failed: invalid NITRO_BANANA_APP_PASSWORD.")
    if r.status_code != 200:
        raise NanoError(f"Login failed: HTTP {r.status_code} {r.text[:200]}")
    token = r.json().get("token")
    if not token:
        raise NanoError(f"Login response missing token: {r.text[:200]}")
    return token


def _get_token(session, server_url, password, cache_path, force=False) -> str:
    if not force:
        cached = _get_cached_token(cache_path)
        if cached:
            return cached
    if not password:
        raise NanoError("No cached token and no password (NITRO_BANANA_APP_PASSWORD).")
    token = _login(session, server_url, password)
    _cache_token(cache_path, token)
    return token


def _call_gemini(session, server_url: str, token: str, payload: dict, timeout: int) -> dict:
    url = f"{server_url.rstrip('/')}/api/gemini"
    headers = {"Authorization": f"Bearer {token}", "X-App-Auth": f"Bearer {token}",
               "Content-Type": "application/json"}
    try:
        r = session.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.exceptions.ConnectionError as e:
        raise NanoError(f"Cannot reach Nitro server at {server_url}. ({e})") from e
    except requests.exceptions.Timeout as e:
        raise NanoError(f"Request timed out after {timeout}s ({e})") from e
    if r.status_code == 401:
        raise AuthExpired("token rejected")
    if r.status_code == 429:
        raise NanoError("QUOTA_EXCEEDED — Gemini quota exhausted, retry later.")
    if r.status_code != 200:
        raise NanoError(f"HTTP {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except json.JSONDecodeError:
        raise NanoError(f"Non-JSON response: {r.text[:200]}")


def generate(prompt: str, refs: "list[Path]", out_dir: Path, *,
             server_url: str, password: "str | None", timeout: int = DEFAULT_TIMEOUT,
             aspect: str = "9:16", token_cache: "Path | None" = None, session=None) -> "list[Path]":
    """Edit-generate one final image with up to 4 base64 refs. Returns saved paths."""
    if aspect not in VALID_ASPECTS:
        raise NanoError(f"Invalid aspect {aspect!r} (valid: {sorted(VALID_ASPECTS)})")
    refs = [Path(r) for r in (refs or [])]
    if len(refs) > MAX_REFS:
        raise NanoError(f"Nano accepts at most {MAX_REFS} reference images, got {len(refs)}")
    session = session or requests
    token_cache = token_cache or DEFAULT_TOKEN_CACHE

    b64s, mimes = encode_inputs(refs) if refs else ([], [])
    payload = {"action": "edit", "base64Datas": b64s, "mimeTypes": mimes,
               "prompt": prompt or "", "aspectRatio": aspect, "imageSize": "1K"}

    token = _get_token(session, server_url, password, token_cache)
    try:
        resp = _call_gemini(session, server_url, token, payload, timeout)
    except AuthExpired:
        token = _get_token(session, server_url, password, token_cache, force=True)
        resp = _call_gemini(session, server_url, token, payload, timeout)

    image = resp.get("imageUrl")
    if not image:
        raise NanoError(f"Response missing imageUrl: {json.dumps(resp)[:200]}")
    out_dir = Path(out_dir)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"nano_{stamp}.png"
    save_image(image, out_path)
    return [out_path]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_nano.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
cd R:/Dev/tools/content-factory
git add gf/backends/nano.py tests/test_nano.py
git commit -m "feat: Nano Banana backend (ported, decoupled)"
```

---

### Task 6: ComfyUI backend (`backends/comfyui.py` + default workflow)

**Files:**
- Create: `R:/Dev/tools/content-factory/gf/workflows/sdxl_txt2img_api.json`
- Create: `R:/Dev/tools/content-factory/gf/backends/comfyui.py`
- Test: `R:/Dev/tools/content-factory/tests/test_comfyui.py`

**Interfaces:**
- Consumes: nothing from other `gf` modules (pure HTTP client).
- Produces:
  - `gf.backends.comfyui.ComfyError(Exception)`
  - `gf.backends.comfyui.load_workflow(path: str | None) -> dict` — loads the given API-format json, or the bundled `sdxl_txt2img_api.json` when `path` is falsy.
  - `gf.backends.comfyui.build_workflow(template: dict, *, ckpt: str, prompt: str, negative: str, n: int, seed: int, width: int, height: int, steps: int, cfg: float) -> dict` — returns a filled copy.
  - `gf.backends.comfyui.generate(prompt: str, out_dir: Path, *, server_url: str, ckpt: str, workflow_path: str | None = None, n: int = 4, negative: str = "", seed: int = 0, width: int = 1024, height: int = 1024, steps: int = 20, cfg: float = 7.0, poll_interval: float = 1.0, timeout: float = 300.0, session=None) -> list[Path]` — submits, polls history, downloads images to `out_dir` as `draft-NN.png`.

REST flow (standard ComfyUI): `POST {url}/prompt` body `{"prompt": <api_workflow>, "client_id": <id>}` → `{"prompt_id": ...}`; poll `GET {url}/history/{prompt_id}` until the id key appears; images at `history[pid]["outputs"][node]["images"]` = `[{"filename","subfolder","type"}]`; download `GET {url}/view?filename=&subfolder=&type=output`.

- [ ] **Step 1: Create the bundled workflow** `gf/workflows/sdxl_txt2img_api.json`

```json
{
  "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "PLACEHOLDER_CKPT"}},
  "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
  "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "PLACEHOLDER_POS", "clip": ["4", 1]}},
  "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "PLACEHOLDER_NEG", "clip": ["4", 1]}},
  "3": {"class_type": "KSampler", "inputs": {
    "seed": 0, "steps": 20, "cfg": 7.0, "sampler_name": "dpmpp_2m", "scheduler": "karras",
    "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
    "latent_image": ["5", 0]}},
  "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
  "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "gf_draft", "images": ["8", 0]}}
}
```

- [ ] **Step 2: Write the failing test** `tests/test_comfyui.py`

```python
import json
from pathlib import Path
import pytest
from gf.backends import comfyui


def test_load_bundled_workflow():
    wf = comfyui.load_workflow(None)
    assert wf["4"]["class_type"] == "CheckpointLoaderSimple"
    assert "9" in wf and wf["9"]["class_type"] == "SaveImage"


def test_build_workflow_substitutes():
    tpl = comfyui.load_workflow(None)
    wf = comfyui.build_workflow(tpl, ckpt="m.safetensors", prompt="a cat",
                                negative="blurry", n=3, seed=42, width=768,
                                height=512, steps=15, cfg=6.0)
    assert wf["4"]["inputs"]["ckpt_name"] == "m.safetensors"
    assert wf["6"]["inputs"]["text"] == "a cat"
    assert wf["7"]["inputs"]["text"] == "blurry"
    assert wf["5"]["inputs"]["batch_size"] == 3
    assert wf["5"]["inputs"]["width"] == 768 and wf["5"]["inputs"]["height"] == 512
    assert wf["3"]["inputs"]["seed"] == 42 and wf["3"]["inputs"]["steps"] == 15
    assert wf["3"]["inputs"]["cfg"] == 6.0
    # original template not mutated
    assert tpl["4"]["inputs"]["ckpt_name"] == "PLACEHOLDER_CKPT"


class _Resp:
    def __init__(self, status, *, jsondata=None, content=b""):
        self.status_code = status
        self._json = jsondata
        self.content = content
        self.text = json.dumps(jsondata) if jsondata is not None else ""

    def json(self):
        return self._json


class _FakeSession:
    def __init__(self):
        self.pid = "pid-1"

    def post(self, url, **kw):
        assert url.endswith("/prompt")
        return _Resp(200, jsondata={"prompt_id": self.pid})

    def get(self, url, **kw):
        if "/history/" in url:
            return _Resp(200, jsondata={self.pid: {"outputs": {"9": {"images": [
                {"filename": "gf_draft_0001.png", "subfolder": "", "type": "output"},
                {"filename": "gf_draft_0002.png", "subfolder": "", "type": "output"},
            ]}}}})
        if "/view" in url:
            return _Resp(200, content=b"IMGBYTES")
        return _Resp(404)


def test_generate_downloads_images(tmp_path):
    out = tmp_path / "drafts"
    saved = comfyui.generate("a cat", out, server_url="http://127.0.0.1:8188",
                             ckpt="m.safetensors", n=2, session=_FakeSession(),
                             poll_interval=0.0)
    assert len(saved) == 2
    assert all(p.exists() and p.read_bytes() == b"IMGBYTES" for p in saved)
    assert saved[0].name == "draft-01.png" and saved[1].name == "draft-02.png"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_comfyui.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gf.backends.comfyui'`

- [ ] **Step 4: Write `gf/backends/comfyui.py`**

```python
"""ComfyUI backend — REST client written from scratch (old agent had no Python client).

Flow: POST /prompt (API-format workflow) -> prompt_id -> poll /history/{id} -> GET /view.
Pure HTTP; no cost/project logic. `session` param defaults to `requests` for test injection.
"""

from __future__ import annotations

import copy
import json
import time
import uuid
from pathlib import Path

import requests

_BUNDLED = Path(__file__).resolve().parent.parent / "workflows" / "sdxl_txt2img_api.json"


class ComfyError(Exception):
    pass


def load_workflow(path: "str | None") -> dict:
    src = Path(path) if path else _BUNDLED
    if not src.exists():
        raise ComfyError(f"Workflow not found: {src}")
    return json.loads(src.read_text(encoding="utf-8"))


def build_workflow(template: dict, *, ckpt: str, prompt: str, negative: str,
                   n: int, seed: int, width: int, height: int, steps: int, cfg: float) -> dict:
    wf = copy.deepcopy(template)
    wf["4"]["inputs"]["ckpt_name"] = ckpt
    wf["6"]["inputs"]["text"] = prompt
    wf["7"]["inputs"]["text"] = negative
    wf["5"]["inputs"]["batch_size"] = n
    wf["5"]["inputs"]["width"] = width
    wf["5"]["inputs"]["height"] = height
    wf["3"]["inputs"]["seed"] = seed
    wf["3"]["inputs"]["steps"] = steps
    wf["3"]["inputs"]["cfg"] = cfg
    return wf


def _submit(session, server_url: str, wf: dict, client_id: str) -> str:
    url = f"{server_url.rstrip('/')}/prompt"
    try:
        r = session.post(url, json={"prompt": wf, "client_id": client_id}, timeout=30)
    except requests.exceptions.ConnectionError as e:
        raise ComfyError(f"Cannot reach ComfyUI at {server_url}. "
                         f"Start it (Q:\\ComfyUI_windows_portable). ({e})") from e
    if r.status_code != 200:
        raise ComfyError(f"POST /prompt failed HTTP {r.status_code}: {r.text[:300]}")
    pid = r.json().get("prompt_id")
    if not pid:
        raise ComfyError(f"No prompt_id in response: {r.text[:200]}")
    return pid


def _poll(session, server_url: str, pid: str, poll_interval: float, timeout: float) -> list:
    url = f"{server_url.rstrip('/')}/history/{pid}"
    deadline = time.time() + timeout
    while True:
        r = session.get(url, timeout=30)
        if r.status_code == 200:
            hist = r.json()
            if pid in hist:
                images = []
                for node in hist[pid].get("outputs", {}).values():
                    images.extend(node.get("images", []))
                return images
        if time.time() > deadline:
            raise ComfyError(f"ComfyUI job {pid} timed out after {timeout}s")
        if poll_interval:
            time.sleep(poll_interval)


def _download(session, server_url: str, image: dict) -> bytes:
    from urllib.parse import urlencode
    params = {"filename": image.get("filename", ""),
              "subfolder": image.get("subfolder", ""),
              "type": image.get("type", "output")}
    url = f"{server_url.rstrip('/')}/view?{urlencode(params)}"
    r = session.get(url, timeout=60)
    if r.status_code != 200:
        raise ComfyError(f"GET /view failed HTTP {r.status_code}")
    return r.content


def generate(prompt: str, out_dir: Path, *, server_url: str, ckpt: str,
             workflow_path: "str | None" = None, n: int = 4, negative: str = "",
             seed: int = 0, width: int = 1024, height: int = 1024, steps: int = 20,
             cfg: float = 7.0, poll_interval: float = 1.0, timeout: float = 300.0,
             session=None) -> "list[Path]":
    session = session or requests
    template = load_workflow(workflow_path)
    wf = build_workflow(template, ckpt=ckpt, prompt=prompt, negative=negative, n=n,
                        seed=seed, width=width, height=height, steps=steps, cfg=cfg)
    client_id = uuid.uuid4().hex
    pid = _submit(session, server_url, wf, client_id)
    images = _poll(session, server_url, pid, poll_interval, timeout)
    if not images:
        raise ComfyError(f"ComfyUI job {pid} produced no images")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, img in enumerate(images, start=1):
        data = _download(session, server_url, img)
        p = out_dir / f"draft-{i:02d}.png"
        p.write_bytes(data)
        saved.append(p)
    return saved
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_comfyui.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
cd R:/Dev/tools/content-factory
git add gf/workflows/sdxl_txt2img_api.json gf/backends/comfyui.py tests/test_comfyui.py
git commit -m "feat: ComfyUI REST backend + default SDXL workflow"
```

---

### Task 7: Core builder + MCP server (`core.py` + `mcp_server.py`)

**Files:**
- Create: `R:/Dev/tools/content-factory/gf/core.py`
- Create: `R:/Dev/tools/content-factory/gf/mcp_server.py`
- Create: `R:/Dev/tools/content-factory/tests/test_mcp.py`

**Interfaces:**
- Consumes: `gf.config.Settings`, `gf.pricing`, `gf.budget`, `gf.media`, `gf.backends.nano`, `gf.backends.comfyui`.
- Produces:
  - `gf.core.Core` dataclass: `settings: Settings`. (Single field for Phase 1; backends are stateless module functions, so `Core` just carries settings. Reused by CLI + server to avoid kf's duplication.)
  - `gf.core.build_core(settings) -> Core`.
  - `gf.mcp_server._generate_draft_impl(project: str, prompt: str, n: int, negative: str, seed: int, *, settings, comfy=comfyui, budget=budget) -> dict`
  - `gf.mcp_server._generate_final_impl(project: str, prompt: str, refs: list, aspect: str, *, settings, nano=nano, budget=budget) -> dict`
  - `gf.mcp_server.build_server() -> tuple[mcp, Settings]`
  - `gf.mcp_server.run_server(http: bool = False) -> None`

`project` is an absolute path to the project folder (Hermes passes it). Impl functions resolve media dirs under it, gate on budget, call the backend, log cost, and return a dict `{"images": [str...], "backend": str, "cost_usd": float, "spent_usd": float}` or `{"error": str, ...}` when the budget blocks. Backends are injected as params (defaulting to the real modules) so tests pass fakes.

- [ ] **Step 1: Write the failing test** `tests/test_mcp.py`

```python
from pathlib import Path
from gf.config import Settings
from gf.mcp_server import _generate_draft_impl, _generate_final_impl


def _settings(tmp_path, cap=None):
    return Settings(
        comfyui_url="http://127.0.0.1:8188", comfyui_ckpt="m.safetensors",
        comfyui_workflow="", nano_server_url="http://localhost:3001", nano_env_file="",
        nano_timeout=120, image_cap_usd=cap, mcp_bind="127.0.0.1", mcp_port=8766,
        mcp_token=None)


class _FakeComfy:
    def generate(self, prompt, out_dir, **kw):
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for i in range(1, kw.get("n", 4) + 1):
            p = out_dir / f"draft-{i:02d}.png"
            p.write_bytes(b"x")
            paths.append(p)
        return paths


class _FakeNano:
    def generate(self, prompt, refs, out_dir, **kw):
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "nano_final.png"
        p.write_bytes(b"y")
        return [p]


def test_draft_impl_generates_and_is_free(tmp_path):
    s = _settings(tmp_path)
    out = _generate_draft_impl(str(tmp_path), "a cat", 2, "", 0,
                               settings=s, comfy=_FakeComfy())
    assert out["backend"] == "comfyui"
    assert out["cost_usd"] == 0.0
    assert len(out["images"]) == 2
    assert all(Path(p).exists() for p in out["images"])


def test_final_impl_generates_and_logs_cost(tmp_path):
    s = _settings(tmp_path)
    out = _generate_final_impl(str(tmp_path), "cinematic", [], "9:16",
                               settings=s, nano=_FakeNano())
    assert out["backend"] == "nano"
    assert out["cost_usd"] > 0
    assert out["spent_usd"] >= out["cost_usd"]
    # cost logged
    assert (tmp_path / "media" / ".gf_cost_log.jsonl").exists()


def test_final_impl_blocked_by_cap(tmp_path):
    s = _settings(tmp_path, cap=0.0)
    out = _generate_final_impl(str(tmp_path), "cinematic", [], "9:16",
                               settings=s, nano=_FakeNano())
    assert "error" in out
    assert out["images"] == []
    # nothing generated
    assert not any((tmp_path / "media").rglob("nano_*.png"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_mcp.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gf.mcp_server'`

- [ ] **Step 3: Write `gf/core.py`**

```python
"""Shared core builder — reused by CLI and MCP server (avoids kf's _core/build_server dup)."""

from dataclasses import dataclass
from .config import Settings, load_settings


@dataclass
class Core:
    settings: Settings


def build_core(settings: "Settings | None" = None) -> Core:
    return Core(settings=settings or load_settings())
```

- [ ] **Step 4: Write `gf/mcp_server.py`**

```python
"""generation-factory MCP server: gf_generate_draft (ComfyUI) + gf_generate_final (Nano)."""

from __future__ import annotations

from pathlib import Path

from . import pricing, budget as budget_mod, media
from .backends import nano as nano_mod, comfyui as comfyui_mod
from .config import load_settings


def _generate_draft_impl(project: str, prompt: str, n: int = 4, negative: str = "",
                         seed: int = 0, *, settings, comfy=comfyui_mod, budget=budget_mod) -> dict:
    project_dir = Path(project)
    date = media.today()
    out_dir = media.drafts_dir(project_dir, date)
    cost = pricing.estimate("comfyui", n)  # 0.0 for local
    gate = budget.check(project_dir, cost, settings.image_cap_usd)
    if not gate["allowed"]:
        return {"error": gate["reason"], "images": [], "backend": "comfyui",
                "cost_usd": cost, "spent_usd": gate["spent"]}
    saved = comfy.generate(prompt, out_dir, server_url=settings.comfyui_url,
                           ckpt=settings.comfyui_ckpt, workflow_path=settings.comfyui_workflow or None,
                           n=n, negative=negative, seed=seed)
    budget.log_cost(project_dir, "comfyui", n, cost, note=f"draft {date}")
    return {"images": [str(p) for p in saved], "backend": "comfyui",
            "cost_usd": cost, "spent_usd": budget.spent(project_dir)}


def _generate_final_impl(project: str, prompt: str, refs: "list" = None, aspect: str = "9:16",
                         *, settings, nano=nano_mod, budget=budget_mod) -> dict:
    project_dir = Path(project)
    refs = [Path(r) for r in (refs or [])]
    date = media.today()
    out_dir = media.drafts_dir(project_dir, date).parent  # generated/<date>/
    cost = pricing.estimate("nano", 1)
    gate = budget.check(project_dir, cost, settings.image_cap_usd)
    if not gate["allowed"]:
        return {"error": gate["reason"], "images": [], "backend": "nano",
                "cost_usd": cost, "spent_usd": gate["spent"]}
    password = _nano_password(settings)
    saved = nano.generate(prompt, refs, out_dir, server_url=settings.nano_server_url,
                          password=password, timeout=settings.nano_timeout, aspect=aspect)
    budget.log_cost(project_dir, "nano", 1, cost, note=f"final {date}")
    return {"images": [str(p) for p in saved], "backend": "nano",
            "cost_usd": cost, "spent_usd": budget.spent(project_dir)}


def _nano_password(settings) -> "str | None":
    """Read NITRO_BANANA_APP_PASSWORD from env or the nitro env file."""
    import os
    pw = os.environ.get("NITRO_BANANA_APP_PASSWORD")
    if pw:
        return pw
    env_file = Path(settings.nano_env_file) if settings.nano_env_file else (
        Path.home() / ".lionfilms" / "nitro_banana.env")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("NITRO_BANANA_APP_PASSWORD="):
                return line.split("=", 1)[1].strip()
    return None


def build_server():
    from mcp.server.fastmcp import FastMCP
    settings = load_settings()
    mcp = FastMCP("generation-factory", host=settings.mcp_bind, port=settings.mcp_port)

    @mcp.tool()
    def gf_generate_draft(project: str, prompt: str, n: int = 4,
                          negative: str = "", seed: int = 0) -> dict:
        """Generate N cheap ComfyUI drafts into <project>/media/generated/<date>/_drafts/."""
        return _generate_draft_impl(project, prompt, n, negative, seed, settings=settings)

    @mcp.tool()
    def gf_generate_final(project: str, prompt: str, refs: list = None,
                          aspect: str = "9:16") -> dict:
        """Generate a client-facing final with Nano Banana (up to 4 multi-image refs)."""
        return _generate_final_impl(project, prompt, refs, aspect, settings=settings)

    return mcp, settings


def run_server(http: bool = False):
    mcp, settings = build_server()
    if not http:
        mcp.run(transport="stdio")
        return
    if settings.mcp_token:
        import hmac
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import JSONResponse
        import uvicorn

        inner = mcp.streamable_http_app()

        class BearerAuth(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                header = request.headers.get("authorization", "")
                if not hmac.compare_digest(header, f"Bearer {settings.mcp_token}"):
                    return JSONResponse({"error": "unauthorized"}, status_code=401)
                return await call_next(request)

        inner.add_middleware(BearerAuth)
        uvicorn.run(inner, host=settings.mcp_bind, port=settings.mcp_port)
    else:
        mcp.run(transport="streamable-http")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_mcp.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
cd R:/Dev/tools/content-factory
git add gf/core.py gf/mcp_server.py tests/test_mcp.py
git commit -m "feat: core builder + MCP server (draft/final tools, 3 transports)"
```

---

### Task 8: CLI (`cli.py`)

**Files:**
- Create: `R:/Dev/tools/content-factory/gf/cli.py`
- Test: `R:/Dev/tools/content-factory/tests/test_cli.py`

**Interfaces:**
- Consumes: `gf.mcp_server.run_server`, `gf.mcp_server._generate_draft_impl/_generate_final_impl`, `gf.config.load_settings`, `gf.__version__`.
- Produces: `gf.cli.app` (Typer), `gf.cli.main()`.

Commands: `version`, `serve --http`, `generate-draft PROJECT PROMPT --n --seed`, `generate-final PROJECT PROMPT --ref (repeatable) --aspect`. The generate-* commands are for manual smoke without Hermes.

- [ ] **Step 1: Write the failing test** `tests/test_cli.py`

```python
from typer.testing import CliRunner
from gf.cli import app

runner = CliRunner()


def test_help_lists_commands():
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    for c in ["version", "serve", "generate-draft", "generate-final"]:
        assert c in r.output


def test_version():
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0
    assert "0.1.0" in r.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gf.cli'`

- [ ] **Step 3: Write `gf/cli.py`**

```python
"""Content Factory CLI — serve the MCP gateway or run one-off generations for smoke tests."""

import json
from typing import List, Optional

import typer

from . import __version__

app = typer.Typer(help="Content Factory (generation-factory) CLI", no_args_is_help=True)


@app.command()
def version():
    """Print version."""
    typer.echo(f"content-factory {__version__}")


@app.command()
def serve(http: bool = typer.Option(False, help="HTTP transport instead of stdio")):
    """Run the generation-factory MCP gateway."""
    from .mcp_server import run_server
    run_server(http=http)


@app.command("generate-draft")
def generate_draft(project: str, prompt: str,
                   n: int = typer.Option(4, help="number of drafts"),
                   negative: str = typer.Option("", help="negative prompt"),
                   seed: int = typer.Option(0, help="seed")):
    """ComfyUI drafts (manual smoke; requires ComfyUI on GF_COMFYUI_URL)."""
    from .config import load_settings
    from .mcp_server import _generate_draft_impl
    out = _generate_draft_impl(project, prompt, n, negative, seed, settings=load_settings())
    typer.echo(json.dumps(out, ensure_ascii=False, indent=2))


@app.command("generate-final")
def generate_final(project: str, prompt: str,
                   ref: Optional[List[str]] = typer.Option(None, help="reference image (repeatable)"),
                   aspect: str = typer.Option("9:16", help="aspect ratio")):
    """Nano Banana final (manual smoke; requires Nitro server on GF_NANO_SERVER_URL)."""
    from .config import load_settings
    from .mcp_server import _generate_final_impl
    out = _generate_final_impl(project, prompt, ref or [], aspect, settings=load_settings())
    typer.echo(json.dumps(out, ensure_ascii=False, indent=2))


def main():
    import sys
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    app()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd R:/Dev/tools/content-factory && python -m pytest tests/test_cli.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full suite**

Run: `cd R:/Dev/tools/content-factory && python -m pytest -v`
Expected: PASS — all tests green (config 2, pricing 3, budget 5, media 4, nano 6, comfyui 3, mcp 3, cli 2 = 28).

- [ ] **Step 6: Commit**

```bash
cd R:/Dev/tools/content-factory
git add gf/cli.py tests/test_cli.py
git commit -m "feat: Typer CLI (serve + generate-draft/final)"
```

---

### Task 9: README, conftest, real Nano smoke

**Files:**
- Create: `R:/Dev/tools/content-factory/README.md`
- Create: `R:/Dev/tools/content-factory/tests/conftest.py`

**Interfaces:**
- Produces: `conftest.py` with a `live` marker gate (tests marked `live` skip unless `GF_RUN_LIVE=1`), matching the kf skip-if-unavailable convention.

- [ ] **Step 1: Create `tests/conftest.py`**

```python
import os
import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("GF_RUN_LIVE") == "1":
        return
    skip_live = pytest.mark.skip(reason="live service test; set GF_RUN_LIVE=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
```

- [ ] **Step 2: Create `README.md`**

```markdown
# Content Factory (`generation-factory`)

Generative MCP layer for the Hermes agent: cheap ComfyUI drafts + Nano Banana finals,
organized into per-project `media/` per the storage spec. Sits alongside `knowledge-factory`.

## Tools (for Hermes)

- `gf_generate_draft(project, prompt, n=4, negative="", seed=0)` — N cheap ComfyUI drafts
  → `<project>/media/generated/<date>/_drafts/draft-NN.png`.
- `gf_generate_final(project, prompt, refs=[], aspect="9:16")` — Nano Banana final (≤4 refs)
  → `<project>/media/generated/<date>/nano_*.png`.

`project` is the absolute path to the project folder.

## Install

    python -m pip install -e ".[dev]"

## Run the gateway

    gf serve            # stdio (local Hermes subprocess) — default
    gf serve --http     # streamable-HTTP on GF_MCP_BIND:GF_MCP_PORT (8766); bearer if GF_MCP_TOKEN set

## Config (env / .env)

See `.env.example`. Key vars: `GF_COMFYUI_URL` (8188), `GF_COMFYUI_CKPT`, `GF_NANO_SERVER_URL`
(3001), `GF_IMAGE_CAP_USD` (soft cap), `GF_MCP_PORT` (8766), `GF_MCP_TOKEN`.

## External services

- **ComfyUI** at `Q:\ComfyUI_windows_portable` — start before using drafts; default `:8188`.
  Default checkpoint `juggernautxl_ragnarok.safetensors` (override `GF_COMFYUI_CKPT`).
- **Nitro Express (Nano Banana)** at `R:\nitro_banana` — `npm run dev:server`, `:3001`.
  Password in `~/.lionfilms/nitro_banana.env` (`NITRO_BANANA_APP_PASSWORD`).

## Tests

    python -m pytest              # unit tests (mocked HTTP)
    GF_RUN_LIVE=1 python -m pytest -m live   # hits real ComfyUI/Nitro

## Cost-gating

Each generation logs an estimate to `<project>/media/.gf_cost_log.jsonl`. If `GF_IMAGE_CAP_USD`
is set, a generation that would push cumulative project spend over the cap is refused.

## Roadmap

Phase 1 (this): skeleton + `gf_generate_draft` + `gf_generate_final`.
Phase 2: `gf_save_asset`, `gf_assemble_shot` (face+location multi-ref), prompt sidecars.
Phase 3: `gf_contact_sheet`, process memory. Phase 4: wire into Hermes `config.yaml`, archive old agent.
```

- [ ] **Step 3: Add a live Nano smoke test** — append to `tests/test_nano.py`

```python
import os


@pytest.mark.live
def test_nano_live_smoke(tmp_path):
    """Real hit against the running Nitro server (:3001). GF_RUN_LIVE=1 to enable."""
    from gf.mcp_server import _nano_password
    from gf.config import load_settings
    s = load_settings()
    pw = _nano_password(s)
    assert pw, "no NITRO_BANANA_APP_PASSWORD available"
    saved = nano.generate("a simple test still, soft light, minimal", [], tmp_path,
                          server_url=s.nano_server_url, password=pw, timeout=s.nano_timeout)
    assert saved and saved[0].exists() and saved[0].stat().st_size > 0
```

- [ ] **Step 4: Run the live smoke (Nitro is up on :3001)**

Run: `cd R:/Dev/tools/content-factory && GF_RUN_LIVE=1 python -m pytest tests/test_nano.py::test_nano_live_smoke -v -s`
Expected: PASS — a real PNG is written to the temp dir (confirms end-to-end Nano path: login → /api/gemini → save). If it fails on auth, verify `~/.lionfilms/nitro_banana.env` has `NITRO_BANANA_APP_PASSWORD`.

- [ ] **Step 5: Run the full default suite once more (live skipped)**

Run: `cd R:/Dev/tools/content-factory && python -m pytest -v`
Expected: PASS — all unit tests green, live test skipped.

- [ ] **Step 6: Commit**

```bash
cd R:/Dev/tools/content-factory
git add README.md tests/conftest.py tests/test_nano.py
git commit -m "docs: README + live Nano smoke test + conftest live gate"
```

---

## Phase 1 Done — Definition

- `gf` package installs; `gf serve` starts a stdio MCP server named `generation-factory` exposing `gf_generate_draft` and `gf_generate_final`.
- Full unit suite green (mocked HTTP for both backends).
- Real Nano smoke confirmed against the live `:3001` server (produces a PNG).
- Cost estimates logged per project; optional soft cap enforced.
- Deferred to later phases: real ComfyUI smoke (start ComfyUI + run `gf generate-draft`), `gf_save_asset`/`gf_assemble_shot` (Phase 2), contact sheets + process memory (Phase 3), Hermes wiring + old-agent archival (Phase 4).

## Deviations from a literal spec reading (intentional)

1. **Cost-gating is a clean rewrite, not a verbatim port.** The old `budget.py`/`pricing.py` are coupled to `00_brief/brief.yaml`, `tools_registry.json`, `cost_log.jsonl`, and `_REPO_ROOT` — exactly the machinery the spec says to drop. We keep only the pricing intent ($0.04/Nano image) and add a decoupled per-project log + optional cap.
2. **ComfyUI client written from scratch** — the old agent had no Python ComfyUI client (only a third-party Node MCP), so there is nothing to port; the spec's "ComfyUI-роутер" is implemented as `backends/comfyui.py`.
3. **Package `gf`, port `8766`** — avoids collision with kf's `8765`; tool prefix `gf_` matches the spec.
4. **Default draft model `juggernautxl_ragnarok.safetensors`** (present on this machine), fully configurable via `GF_COMFYUI_CKPT` / `GF_COMFYUI_WORKFLOW`.
```
