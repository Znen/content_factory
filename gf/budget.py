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
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            try:
                total += float(record.get("cost_usd", 0.0))
            except (TypeError, ValueError):
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
