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
