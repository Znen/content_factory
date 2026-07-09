"""Реестр видео-задач Dreamina: <project>/media/.gf_video_jobs.jsonl.

Завод сам помнит `submit_id` задач, чтобы Hermes/Кир не были обязаны их держать.
Запись при submit (pending/success), обновление при fetch (success+output или fail).
По стилю budget.py — одна строка JSON на задачу; обновление переписывает файл.
"""

import json
import time
from pathlib import Path

_REG_NAME = ".gf_video_jobs.jsonl"


def _reg_path(project_dir: Path) -> Path:
    return Path(project_dir) / "media" / _REG_NAME


def append_job(project_dir: Path, job: dict) -> None:
    """Добавить задачу в реестр. `ts` проставляется, если не задан."""
    path = _reg_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": time.time(), **job}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_jobs(project_dir: Path) -> "list[dict]":
    path = _reg_path(project_dir)
    if not path.exists():
        return []
    out = []
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


def update_job(project_dir: Path, submit_id: str, **changes) -> bool:
    """Обновить поля задачи по submit_id (переписывает файл). True, если нашлась."""
    jobs = read_jobs(project_dir)
    found = False
    for rec in jobs:
        if rec.get("submit_id") == submit_id:
            rec.update(changes)
            found = True
    if found:
        path = _reg_path(project_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for rec in jobs:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return found
