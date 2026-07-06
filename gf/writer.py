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
    # YAML парсит неквотированный `updated: 2026-07-06` как datetime.date —
    # не JSON-сериализуемо (падает в gf_list_targets/CLI echo и живом MCP-ответе).
    if hasattr(meta.get("updated"), "isoformat"):
        meta["updated"] = meta["updated"].isoformat()
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


_EMIT_TOOL = {
    "name": "emit_prompt",
    "description": "Верни финальный промпт для генеративной модели.",
    "input_schema": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "готовый промпт, по правилам паспорта"},
            "negative": {"type": ["string", "null"]},
            "params": {"type": ["object", "null"],
                       "description": "рекомендации параметров площадки (steps/cfg/...)"},
            "notes": {"type": ["string", "null"], "description": "коротко: почему так"},
        },
        "required": ["prompt"],
    },
}

_SYSTEM_ROLE = (
    "Ты — промпт-инженер для генеративных моделей изображений/видео. "
    "Пиши промпт СТРОГО по правилам паспорта модели ниже. Промпт — на английском, "
    "если паспорт не требует иного. Ответь только вызовом инструмента emit_prompt.\n\n"
    "=== ПАСПОРТ МОДЕЛИ ===\n"
)


def load_style(project: str) -> "str | None":
    path = Path(project) / "prompts" / "style.md"
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _build_user(task: str, style: "str | None", refs: "list | None",
                aspect: "str | None", extra: "str | None") -> str:
    parts = [f"## Задача\n{task}"]
    if style:
        parts.append(f"## Стиль проекта\n{style}")
    if refs:
        names = "\n".join(f"- {r}" for r in refs)
        parts.append(f"## Референсы (имена файлов; сами изображения не приложены)\n{names}")
    if aspect:
        parts.append(f"## Аспект\n{aspect}")
    if extra:
        parts.append(f"## Дополнительные указания\n{extra}")
    return "\n\n".join(parts)


def _call_claude(client, settings, system: str, user: str, usage_acc: dict) -> dict:
    """Один forced tool call (+1 ретрай на битой схеме). Usage КАЖДОГО ответа
    добавляется в usage_acc — каждый вызов оплачен, даже если схема битая."""
    import anthropic
    last = None
    for _ in range(2):  # 1 попытка + 1 ретрай на битой схеме
        try:
            resp = client.messages.create(
                model=settings.writer_model,
                max_tokens=settings.writer_max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                tools=[_EMIT_TOOL],
                tool_choice={"type": "tool", "name": "emit_prompt"},
            )
        except anthropic.APIError as e:
            raise WriterError(f"Claude API error: {e}") from e
        except TypeError as e:
            # Anthropic SDK валидирует auth-заголовки лениво (внутри _build_request,
            # не в конструкторе клиента) и на отсутствующем ключе кидает голый
            # TypeError, а не APIError — без этого перехвата смоук без ключа
            # падает traceback'ом вместо чистого {"error": ...} (fail-closed).
            raise WriterError(f"Claude API error (клиент/ключ): {e}") from e
        usage = getattr(resp, "usage", None)
        usage_acc["in"] += getattr(usage, "input_tokens", 0) or 0
        usage_acc["out"] += getattr(usage, "output_tokens", 0) or 0
        block = next((b for b in resp.content if getattr(b, "type", "") == "tool_use"), None)
        data = dict(block.input) if block is not None else {}
        if isinstance(data.get("prompt"), str) and data["prompt"].strip():
            return data
        last = data
    raise WriterError(f"Райтер вернул невалидный ответ дважды: {last!r}")


def _make_client():
    try:
        import anthropic
        return anthropic.Anthropic(max_retries=1)
    except Exception as e:  # нет пакета или ключа
        raise WriterError(f"Не удалось создать Anthropic-клиент (ANTHROPIC_API_KEY?): {e}") from e


def log_prompt(project: str, target: str, task: str, result: dict) -> Path:
    from . import media
    slug = target.rsplit("/", 1)[-1]
    date = media.today()
    out_dir = Path(project) / "prompts"
    out_dir.mkdir(parents=True, exist_ok=True)
    idx = media.next_index(out_dir, f"{date}-{slug}", ext=".md")
    path = out_dir / f"{date}-{slug}-{idx:02d}.md"
    import json
    body = (f"# {target} — {date}\n\n## Задача\n{task}\n\n## Промпт\n{result['prompt']}\n\n"
            f"## Negative\n{result.get('negative') or '—'}\n\n"
            f"## Params (рекомендация)\n```json\n{json.dumps(result.get('params'), ensure_ascii=False)}\n```\n\n"
            f"## Notes\n{result.get('notes') or '—'}\n")
    path.write_text(body, encoding="utf-8")
    return path


def write_prompt(project: str, target: str, task: str, refs: "list | None" = None,
                 aspect: "str | None" = None, extra: "str | None" = None, *,
                 settings, client=None, root: "Path | None" = None,
                 budget=None) -> dict:
    from . import budget as budget_mod, pricing
    budget = budget or budget_mod
    if not settings.writer_enabled:
        raise WriterError("Райтер выключен (GF_WRITER_ENABLED=false). Включи и перезапусти.")
    passport = load_passport(target, root=root)
    system = _SYSTEM_ROLE + passport["body"]
    user = _build_user(task, load_style(project), refs, aspect, extra)
    client = client or _make_client()
    usage_acc = {"in": 0, "out": 0}
    try:
        data = _call_claude(client, settings, system, user, usage_acc)
    finally:
        # каждый ответ API оплачен — логируем суммарную стоимость всех попыток,
        # даже если райтер в итоге упал (битая схема дважды / APIError на ретрае)
        if usage_acc["in"] or usage_acc["out"]:
            cost = pricing.estimate_llm(settings.writer_model,
                                        usage_acc["in"], usage_acc["out"])
            budget.log_cost(Path(project), "writer", 1, cost, note=f"prompt {target}")
    result = {"prompt": data["prompt"].strip(), "negative": data.get("negative"),
              "params": data.get("params"), "notes": data.get("notes"),
              "target": target, "log_path": None, "warning": None}
    try:
        result["log_path"] = str(log_prompt(project, target, task, result))
    except OSError as e:
        result["warning"] = f"Промпт готов, но лог не записался: {e}"
    return result
