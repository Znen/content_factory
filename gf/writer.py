"""Prompt writer: паспорта моделей (promptdocs/) + один вызов Claude -> готовый промпт.

Паспорт = markdown с YAML-frontmatter. Обязательные ключи фронтматтера:
target, platform, syntax, negative, refs, updated. Файлы `_*.md` — справочники,
не цели. Fail-closed здесь; fail-open — на стороне вызывающего (mcp_server).
"""

from __future__ import annotations

from pathlib import Path

PROMPTDOCS = Path(__file__).resolve().parent / "promptdocs"
_REQUIRED_META = {"target", "platform", "syntax", "negative", "refs", "updated"}


class WriterError(Exception):
    pass


def _parse_passport(path: Path) -> dict:
    import yaml
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise WriterError(f"Passport {path}: нет YAML-frontmatter (файл должен начинаться с ---)")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise WriterError(f"Passport {path}: frontmatter не закрыт вторым ---")
    try:
        meta = yaml.safe_load(parts[1])
    except yaml.YAMLError as e:
        raise WriterError(f"Passport {path}: битый YAML во frontmatter: {e}") from e
    if not isinstance(meta, dict) or not _REQUIRED_META <= set(meta):
        missing = sorted(_REQUIRED_META - set(meta or {}))
        raise WriterError(f"Passport {path}: во frontmatter нет ключей {missing}")
    return {"meta": meta, "body": parts[2].strip()}


def list_targets(root: "Path | None" = None) -> "list[dict]":
    root = Path(root) if root else PROMPTDOCS
    if not root.exists():
        return []
    out = []
    for p in sorted(root.rglob("*.md")):
        if p.name.startswith("_"):
            continue
        out.append(_parse_passport(p)["meta"])
    return out


def load_passport(target: str, root: "Path | None" = None) -> dict:
    root = Path(root) if root else PROMPTDOCS
    path = root / f"{target}.md"
    if not path.exists():
        known = ", ".join(t["target"] for t in list_targets(root)) or "<пусто>"
        raise WriterError(f"Неизвестная цель '{target}'. Доступные: {known}")
    return _parse_passport(path)
