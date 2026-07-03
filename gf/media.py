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
