# Промпт-слой (writer) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Слой промпт-инженерии внутри gf: однопроходный Claude-райтер пишет промпты для ComfyUI/Nano/Magnific по паспортам моделей (`gf/promptdocs/`); Hermes получает `gf_write_prompt`/`gf_list_targets` + авто-переписывание в `gf_generate_*`.

**Architecture:** По спеке `docs/superpowers/specs/2026-07-06-prompt-layer-design.md`. Новый модуль `gf/writer.py` (чистая функция, один вызов Claude Messages API с forced tool call), паспорта = markdown с YAML-frontmatter, лог промптов в `<project>/prompts/`. Fail-closed в явном пути, fail-open с флагом `writer_skipped` в авто-пути.

**Tech Stack:** Python 3.10+, `anthropic` SDK (Messages API, forced tool use), `pyyaml` (frontmatter), pytest с инжектируемым `client=` (паттерн `session=requests` из comfyui.py).

## Global Constraints

- Тесты не ходят в живые API; live-проверки только вручную через CLI (паттерн `@pytest.mark.live` / `GF_RUN_LIVE`).
- Модель райтера по умолчанию: `claude-sonnet-5` (точная строка), конфигурируемо через `GF_WRITER_MODEL`. Параметр `thinking` НЕ передавать (на Sonnet 5 адаптивный по умолчанию; explicit `disabled` ломает fable-5). `temperature`/`top_p`/`top_k` НЕ передавать (400 на Sonnet 5).
- Ключ — стандартный `ANTHROPIC_API_KEY` (env / `.env` через python-dotenv, уже подхватывается в `config.load_settings`).
- **Отступление от буквы спеки (зафиксировать в АРХИТЕКТУРА.md §8):** паспорта живут в `gf/promptdocs/` (внутри пакета, как `gf/workflows/`), а не в корне репо — иначе они не попадают в package-data и ломается установка пакета.
- Комментарии/докстринги — в стиле репо (короткие, по-русски или по-английски как в соседних файлах).
- Коммит после каждой задачи. Сообщения — в стиле репо (`feat:`/`fix:`/`docs:` + русский).

---

### Task 1: Зависимости и конфиг райтера

**Files:**
- Modify: `pyproject.toml`
- Modify: `gf/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: поля `Settings`: `writer_model: str`, `writer_max_tokens: int`, `writer_enabled: bool`, `writer_draft_target: str`, `writer_final_target: str`. Env: `GF_WRITER_MODEL`, `GF_WRITER_MAX_TOKENS`, `GF_WRITER_ENABLED`, `GF_WRITER_DRAFT_TARGET`, `GF_WRITER_FINAL_TARGET`.

- [ ] **Step 1: Write the failing test** — добавить в `tests/test_config.py`:

```python
def test_writer_settings_defaults(monkeypatch):
    for var in ("GF_WRITER_MODEL", "GF_WRITER_MAX_TOKENS", "GF_WRITER_ENABLED",
                "GF_WRITER_DRAFT_TARGET", "GF_WRITER_FINAL_TARGET"):
        monkeypatch.delenv(var, raising=False)
    from gf.config import load_settings
    s = load_settings()
    assert s.writer_model == "claude-sonnet-5"
    assert s.writer_max_tokens == 2000
    assert s.writer_enabled is True
    assert s.writer_draft_target == "comfyui/sdxl-juggernaut"
    assert s.writer_final_target == "nano/gemini-image"


def test_writer_settings_overrides(monkeypatch):
    monkeypatch.setenv("GF_WRITER_MODEL", "claude-haiku-4-5")
    monkeypatch.setenv("GF_WRITER_ENABLED", "false")
    from gf.config import load_settings
    s = load_settings()
    assert s.writer_model == "claude-haiku-4-5"
    assert s.writer_enabled is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v -k writer`
Expected: FAIL — `TypeError`/`AttributeError` (нет полей writer_*)

- [ ] **Step 3: Implement** — в `gf/config.py`: добавить поля в dataclass и загрузку:

```python
# в @dataclass Settings (после mcp_token):
    writer_model: str
    writer_max_tokens: int
    writer_enabled: bool
    writer_draft_target: str
    writer_final_target: str


def _bool(raw: str, default: bool) -> bool:
    raw = (raw or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")

# в load_settings(), внутри return Settings(...):
        writer_model=os.environ.get("GF_WRITER_MODEL", "claude-sonnet-5"),
        writer_max_tokens=int(os.environ.get("GF_WRITER_MAX_TOKENS", "2000")),
        writer_enabled=_bool(os.environ.get("GF_WRITER_ENABLED", ""), True),
        writer_draft_target=os.environ.get("GF_WRITER_DRAFT_TARGET", "comfyui/sdxl-juggernaut"),
        writer_final_target=os.environ.get("GF_WRITER_FINAL_TARGET", "nano/gemini-image"),
```

В `pyproject.toml` dependencies добавить `"anthropic>=0.50"` и `"pyyaml>=6.0"`; в `[tool.setuptools.package-data]` строку `gf = ["workflows/*.json", "promptdocs/**/*.md"]`. Установить: `pip install -e .[dev]`.

⚠️ Существующие тесты строят `Settings(...)` позиционно/по именам (`tests/test_mcp.py::_settings`) — новые поля дать в конец dataclass; `_settings` в тестах обновить (Task 6 их трогает; здесь добавить в `_settings` хелпер `tests/test_mcp.py` значения по умолчанию сразу, чтобы суита не падала):

```python
# tests/test_mcp.py::_settings — добавить в конструктор:
        writer_model="claude-sonnet-5", writer_max_tokens=2000,
        writer_enabled=False, writer_draft_target="comfyui/sdxl-juggernaut",
        writer_final_target="nano/gemini-image",
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/ -q`
Expected: все зелёные (текущая суита 80+ passed, +2 новых)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml gf/config.py tests/test_config.py tests/test_mcp.py
git commit -m "feat: конфиг промпт-райтера (GF_WRITER_*) + deps anthropic/pyyaml"
```

---

### Task 2: Паспорта — загрузчик и список целей

**Files:**
- Create: `gf/writer.py`
- Create: `gf/promptdocs/` (директория; появится с первым паспортом в Task 3)
- Test: `tests/test_writer.py`

**Interfaces:**
- Produces:
  - `writer.WriterError(Exception)` — единственное публичное исключение модуля;
  - `writer.load_passport(target: str, root: Path | None = None) -> dict` — `{"meta": dict, "body": str}`; `WriterError` если цели нет (с перечнем доступных) или битый frontmatter;
  - `writer.list_targets(root: Path | None = None) -> list[dict]` — метаданные всех паспортов (файлы `_*.md` пропускаются);
  - `writer.PROMPTDOCS: Path` — дефолтный корень `gf/promptdocs/`;
  - обязательные ключи frontmatter: `target, platform, syntax, negative, refs, updated`.

- [ ] **Step 1: Write the failing tests** — `tests/test_writer.py`:

```python
from pathlib import Path

import pytest

from gf import writer

PASSPORT = """---
target: comfyui/sdxl-test
platform: comfyui
syntax: tags
negative: true
refs: none
updated: 2026-07-06
---
# Как писать промпт
Тело гайда.
"""


def _docs(tmp_path) -> Path:
    root = tmp_path / "promptdocs"
    (root / "comfyui").mkdir(parents=True)
    (root / "comfyui" / "sdxl-test.md").write_text(PASSPORT, encoding="utf-8")
    return root


def test_load_passport_ok(tmp_path):
    p = writer.load_passport("comfyui/sdxl-test", root=_docs(tmp_path))
    assert p["meta"]["platform"] == "comfyui"
    assert "Тело гайда" in p["body"]


def test_load_passport_unknown_target_lists_available(tmp_path):
    with pytest.raises(writer.WriterError) as e:
        writer.load_passport("magnific/nope", root=_docs(tmp_path))
    assert "comfyui/sdxl-test" in str(e.value)


def test_load_passport_broken_frontmatter(tmp_path):
    root = _docs(tmp_path)
    (root / "comfyui" / "bad.md").write_text("no frontmatter here", encoding="utf-8")
    with pytest.raises(writer.WriterError) as e:
        writer.load_passport("comfyui/bad", root=root)
    assert "bad.md" in str(e.value)


def test_list_targets_skips_catalog_files(tmp_path):
    root = _docs(tmp_path)
    (root / "magnific").mkdir()
    (root / "magnific" / "_catalog.md").write_text("справочник", encoding="utf-8")
    targets = writer.list_targets(root=root)
    assert [t["target"] for t in targets] == ["comfyui/sdxl-test"]


def test_real_promptdocs_have_valid_frontmatter():
    """Каждый настоящий паспорт в gf/promptdocs валиден (Ф-П1 quality gate)."""
    if not writer.PROMPTDOCS.exists():
        pytest.skip("promptdocs ещё не созданы")
    for t in writer.list_targets():
        assert t["target"], t
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_writer.py -v`
Expected: FAIL — `ImportError: cannot import name 'writer'`

- [ ] **Step 3: Implement** — `gf/writer.py` (первая часть модуля):

```python
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
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_writer.py -v`
Expected: PASS (последний тест — skip, promptdocs ещё нет)

- [ ] **Step 5: Commit**

```bash
git add gf/writer.py tests/test_writer.py
git commit -m "feat: загрузчик паспортов моделей (promptdocs, frontmatter, list_targets)"
```

---

### Task 3: Паспорт ComfyUI/SDXL (исследование → файл)

**Files:**
- Create: `gf/promptdocs/comfyui/sdxl-juggernaut.md`

**Interfaces:**
- Produces: цель `comfyui/sdxl-juggernaut` (её ждёт `writer_draft_target` из Task 1).

Это исследовательская задача: дистиллировать готовые скилы в паспорт. Исполнитель работает с WebFetch/WebSearch, код не пишет.

- [ ] **Step 1: Собрать источники.** Прочитать (WebFetch страницы skills.sh и/или SKILL.md в GitHub-репо автора):
  - `https://skills.sh/mckruz/comfyui-expert/comfyui-prompt-engineer` (основной — промптинг SD/SDXL в ComfyUI);
  - `https://skills.sh/replicate/skills/prompt-images` (общие принципы image-промптинга);
  - `https://skills.sh/davila7/claude-code-templates/stable-diffusion-image-generation`;
  - WebSearch: «JuggernautXL prompting guide recommended settings» (чекпоинт завода — `juggernautxl_ragnarok.safetensors`, см. `GF_COMFYUI_CKPT`).

- [ ] **Step 2: Написать паспорт** по шаблону (этот шаблон обязателен для всех паспортов Ф-П1):

```markdown
---
target: comfyui/sdxl-juggernaut
platform: comfyui
syntax: tags            # tags | natural | hybrid
max_len: 300            # ориентир длины промпта в токенах
negative: true
refs: none              # none | single | multi(N)
sources: [mckruz/comfyui-expert@comfyui-prompt-engineer, replicate/skills@prompt-images]
updated: 2026-07-06
---
# Как писать промпт для ComfyUI / SDXL (JuggernautXL)

## Структура промпта
<порядок блоков: субъект -> действие -> окружение -> стиль -> свет -> камера -> качество-теги;
что идёт первым и почему; использование весов (word:1.2) и когда их НЕ использовать>

## Negative prompt
<базовый негатив для JuggernautXL; что докидывать по типу задачи>

## Параметры (рекомендации для params)
<steps/cfg/размеры под SDXL 1024x1024, портрет/пейзаж>

## Типовые фейлы
<анатомия, текст в кадре, мульти-персонажность...>

## Примеры «задача -> плохо -> хорошо»
<3-5 пар, минимум один пример на кириллическую задачу -> английский промпт>
```

- [ ] **Step 3: Проверить валидность**

Run: `python -m pytest tests/test_writer.py::test_real_promptdocs_have_valid_frontmatter -v`
Expected: PASS (уже не skip)

- [ ] **Step 4: Commit**

```bash
git add gf/promptdocs/comfyui/sdxl-juggernaut.md
git commit -m "docs: паспорт comfyui/sdxl-juggernaut (дистилляция comfyui-expert + replicate)"
```

---

### Task 4: Паспорт Nano/Gemini (исследование → файл)

**Files:**
- Create: `gf/promptdocs/nano/gemini-image.md`

**Interfaces:**
- Produces: цель `nano/gemini-image` (её ждёт `writer_final_target`).

- [ ] **Step 1: Собрать источники.** WebFetch/WebSearch:
  - `https://skills.sh/everyinc/compound-engineering-plugin/ce-gemini-imagegen` и `https://skills.sh/johnlindquist/claude/gemini-image`;
  - официальный гайд Google по image prompting для Gemini (WebSearch «Gemini image generation prompting guide»);
  - учесть специфику Nano: натуральный язык (не теги), multi-image референсы до 4 (см. `gf_generate_final`), aspect передаётся отдельным параметром — в промпт его писать не надо.

- [ ] **Step 2: Написать паспорт** по шаблону из Task 3 с frontmatter:

```markdown
---
target: nano/gemini-image
platform: nano
syntax: natural
max_len: 500
negative: false
refs: multi(4)
sources: [everyinc/compound-engineering-plugin@ce-gemini-imagegen, johnlindquist/claude@gemini-image]
updated: 2026-07-06
---
```

Секции: структура описательного промпта (сцена как связный абзац), как ссылаться на референсы («the person from the first image...»), чего Gemini не умеет/запрещает, примеры «плохо → хорошо».

- [ ] **Step 3: Проверить валидность** — `python -m pytest tests/test_writer.py -v` → PASS

- [ ] **Step 4: Commit**

```bash
git add gf/promptdocs/nano/gemini-image.md
git commit -m "docs: паспорт nano/gemini-image (натуральный язык, multi-ref)"
```

---

### Task 5: Паспорта Magnific (3-5 моделей) + справочник каталога

**Files:**
- Create: `gf/promptdocs/magnific/<model>.md` (3–5 файлов, имена по slug моделей, напр. `mystic.md`, `flux-kontext.md`, ...)
- Create: `gf/promptdocs/magnific/_catalog.md`

**Interfaces:**
- Produces: цели `magnific/<model>` + справочник `_catalog.md` (не цель, файл с `_`).

- [ ] **Step 1: Получить живой каталог моделей.** Основной путь — веб-доки Freepik (Magnific = Freepik-платформа): WebSearch «Freepik API image generation models list», WebFetch доков API (Mystic, Flux, Imagen, Seedream и т.п.). Дополнительно, если доступно: попросить Кира дёрнуть `images_models_list`/`video_models_list` через Hermes и вставить вывод — живой каталог точнее веба. Если живой каталог недоступен — работаем по веб-докам, в `_catalog.md` пометить источник и дату.

- [ ] **Step 2: Выбрать рабочий набор (3–5 моделей)** по критериям: (а) t2i с multi-ref (кандидат на финалы вместо заблокированного Nano), (б) фотореализм/кино-стилистика под задачи Лион Филмс, (в) есть видео-модель — минимум одна (video_generate уже используется Hermes'ом). Зафиксировать выбор и обоснование в `_catalog.md`.

- [ ] **Step 3: Написать паспорта** по шаблону Task 3 (frontmatter: `platform: magnific`, `refs:` по возможностям модели). Обязательная секция для magnific-паспортов — «Особенности площадки»: кредиты (`simulate_cost` перед дорогой генерацией), upload-флоу для локальных файлов (`creations_request_upload` → PUT → `creations_finalize_upload`; `creations_upload_image` — только для http(s)-URL), поведение при circuit-breaker (см. память hermes-integration).

- [ ] **Step 4: Написать `_catalog.md`** — таблица «модель → когда брать → чем платим», по строке на модель каталога (коротко), ссылки на подробные паспорта рабочего набора.

- [ ] **Step 5: Проверить валидность** — `python -m pytest tests/test_writer.py -v` → PASS

- [ ] **Step 6: Commit**

```bash
git add gf/promptdocs/magnific/
git commit -m "docs: паспорта magnific (рабочий набор) + справочник каталога"
```

**Checkpoint:** после Task 5 показать все паспорта Киру на ревью (quality gate Ф-П1) — правки дёшевы, файлы в git.

---

### Task 6: Ядро райтера — write_prompt (контекст → Claude → лог → стоимость)

**Files:**
- Modify: `gf/writer.py`
- Modify: `gf/pricing.py`
- Test: `tests/test_writer.py`

**Interfaces:**
- Consumes: `load_passport`/`list_targets` (Task 2), `Settings.writer_*` (Task 1), `budget.log_cost`, `media.next_index`.
- Produces:
  - `writer.write_prompt(project: str, target: str, task: str, refs: list | None = None, aspect: str | None = None, extra: str | None = None, *, settings, client=None, root=None) -> dict` — ключи: `prompt: str`, `negative: str|None`, `params: dict|None`, `notes: str|None`, `target: str`, `log_path: str|None`, `warning: str|None`;
  - `writer.load_style(project) -> str | None`;
  - `pricing.estimate_llm(model: str, input_tokens: int, output_tokens: int) -> float`;
  - клиент в тестах: объект с `messages.create(**kw)` → response с `.content` (список блоков с `.type`/`.input`) и `.usage` (`.input_tokens`/`.output_tokens`).

- [ ] **Step 1: Write the failing tests** — добавить в `tests/test_writer.py`:

```python
import json

from gf.config import Settings


def _settings(enabled=True):
    return Settings(
        comfyui_url="http://127.0.0.1:8188", comfyui_ckpt="m.safetensors",
        comfyui_workflow="", nano_server_url="http://localhost:3001", nano_env_file="",
        nano_timeout=120, image_cap_usd=None, mcp_bind="127.0.0.1", mcp_port=8766,
        mcp_token=None, writer_model="claude-sonnet-5", writer_max_tokens=2000,
        writer_enabled=enabled, writer_draft_target="comfyui/sdxl-test",
        writer_final_target="nano/gemini-image")


class _Block:
    type = "tool_use"

    def __init__(self, payload):
        self.input = payload


class _Usage:
    input_tokens = 1000
    output_tokens = 200


class _Resp:
    def __init__(self, payload):
        self.content = [_Block(payload)]
        self.usage = _Usage()


class _FakeClient:
    def __init__(self, payloads):
        self.calls = []
        self._payloads = list(payloads)

        outer = self

        class _Messages:
            def create(self, **kw):
                outer.calls.append(kw)
                return _Resp(outer._payloads.pop(0))

        self.messages = _Messages()


GOOD = {"prompt": "cinematic photo, rain", "negative": "blurry",
        "params": {"steps": 30}, "notes": "ok"}


def test_write_prompt_happy_path(tmp_path):
    root = _docs(tmp_path)
    fake = _FakeClient([GOOD])
    out = writer.write_prompt(str(tmp_path), "comfyui/sdxl-test", "Кадр 1: дождь",
                              settings=_settings(), client=fake, root=root)
    assert out["prompt"] == "cinematic photo, rain"
    assert out["negative"] == "blurry"
    assert out["target"] == "comfyui/sdxl-test"
    # системный промпт содержит тело паспорта, user — задачу
    kw = fake.calls[0]
    assert "Тело гайда" in kw["system"]
    assert "Кадр 1: дождь" in kw["messages"][0]["content"]
    assert kw["tool_choice"] == {"type": "tool", "name": "emit_prompt"}
    assert "temperature" not in kw and "thinking" not in kw


def test_write_prompt_includes_style_and_refs(tmp_path):
    root = _docs(tmp_path)
    style = tmp_path / "prompts"
    style.mkdir()
    (style / "style.md").write_text("тёплая плёнка", encoding="utf-8")
    fake = _FakeClient([GOOD])
    writer.write_prompt(str(tmp_path), "comfyui/sdxl-test", "задача",
                        refs=["cast/kurtukova/winner.png"], aspect="9:16",
                        extra="меньше тумана", settings=_settings(), client=fake, root=root)
    user = fake.calls[0]["messages"][0]["content"]
    assert "тёплая плёнка" in user
    assert "kurtukova" in user
    assert "9:16" in user and "меньше тумана" in user


def test_write_prompt_logs_to_prompts_dir_and_costs(tmp_path):
    root = _docs(tmp_path)
    out = writer.write_prompt(str(tmp_path), "comfyui/sdxl-test", "задача",
                              settings=_settings(), client=_FakeClient([GOOD]), root=root)
    log = Path(out["log_path"])
    assert log.exists() and log.parent == tmp_path / "prompts"
    assert log.name.endswith("-sdxl-test-01.md")
    assert "cinematic photo, rain" in log.read_text(encoding="utf-8")
    # стоимость из usage попала в бюджет-лог
    cost_log = (tmp_path / "media" / ".gf_cost_log.jsonl").read_text(encoding="utf-8")
    rec = json.loads(cost_log.strip().splitlines()[-1])
    assert rec["backend"] == "writer" and rec["cost_usd"] > 0


def test_write_prompt_log_numbering_continues(tmp_path):
    root = _docs(tmp_path)
    writer.write_prompt(str(tmp_path), "comfyui/sdxl-test", "a",
                        settings=_settings(), client=_FakeClient([GOOD]), root=root)
    out2 = writer.write_prompt(str(tmp_path), "comfyui/sdxl-test", "b",
                               settings=_settings(), client=_FakeClient([GOOD]), root=root)
    assert out2["log_path"].endswith("-sdxl-test-02.md")


def test_write_prompt_retries_once_on_bad_schema(tmp_path):
    root = _docs(tmp_path)
    fake = _FakeClient([{"nope": 1}, GOOD])  # первый ответ без prompt
    out = writer.write_prompt(str(tmp_path), "comfyui/sdxl-test", "задача",
                              settings=_settings(), client=fake, root=root)
    assert out["prompt"] == "cinematic photo, rain"
    assert len(fake.calls) == 2


def test_write_prompt_fails_after_two_bad_schemas(tmp_path):
    root = _docs(tmp_path)
    with pytest.raises(writer.WriterError):
        writer.write_prompt(str(tmp_path), "comfyui/sdxl-test", "задача",
                            settings=_settings(),
                            client=_FakeClient([{"nope": 1}, {"nope": 2}]), root=root)


def test_write_prompt_disabled_raises(tmp_path):
    with pytest.raises(writer.WriterError) as e:
        writer.write_prompt(str(tmp_path), "comfyui/sdxl-test", "задача",
                            settings=_settings(enabled=False),
                            client=_FakeClient([GOOD]), root=_docs(tmp_path))
    assert "GF_WRITER_ENABLED" in str(e.value)


def test_estimate_llm_pricing():
    from gf import pricing
    # sonnet-5: $3/M in + $15/M out
    assert pricing.estimate_llm("claude-sonnet-5", 1_000_000, 0) == 3.0
    assert pricing.estimate_llm("claude-sonnet-5", 0, 1_000_000) == 15.0
    assert pricing.estimate_llm("unknown-model", 1_000_000, 0) == 5.0  # дефолт
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_writer.py -v`
Expected: FAIL — `AttributeError: module 'gf.writer' has no attribute 'write_prompt'` и т.п.

- [ ] **Step 3: Implement.** В `gf/pricing.py` добавить:

```python
_TOKEN_USD_PER_MTOK = {
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-opus-4-8": (5.0, 25.0),
}
_DEFAULT_TOKEN_USD = (5.0, 25.0)


def estimate_llm(model: str, input_tokens: int, output_tokens: int) -> float:
    """USD за один LLM-вызов по usage-токенам. Неизвестная модель -> консервативный дефолт."""
    inp, out = _TOKEN_USD_PER_MTOK.get(model, _DEFAULT_TOKEN_USD)
    return round((max(0, input_tokens) * inp + max(0, output_tokens) * out) / 1_000_000, 4)
```

В `gf/writer.py` дописать (после загрузчика паспортов):

```python
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


def _call_claude(client, settings, system: str, user: str) -> "tuple[dict, object]":
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
        block = next((b for b in resp.content if getattr(b, "type", "") == "tool_use"), None)
        data = dict(block.input) if block is not None else {}
        if isinstance(data.get("prompt"), str) and data["prompt"].strip():
            return data, resp.usage
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
    data, usage = _call_claude(client, settings, system, user)
    cost = pricing.estimate_llm(settings.writer_model,
                                getattr(usage, "input_tokens", 0),
                                getattr(usage, "output_tokens", 0))
    budget.log_cost(Path(project), "writer", 1, cost, note=f"prompt {target}")
    result = {"prompt": data["prompt"].strip(), "negative": data.get("negative"),
              "params": data.get("params"), "notes": data.get("notes"),
              "target": target, "log_path": None, "warning": None}
    try:
        result["log_path"] = str(log_prompt(project, target, task, result))
    except OSError as e:
        result["warning"] = f"Промпт готов, но лог не записался: {e}"
    return result
```

⚠️ `media.next_index` матчит `^{prefix}-(\d+){ext}$` — префикс `f"{date}-{slug}"` даёт файлы `2026-07-06-sdxl-test-01.md`, нумерация продолжается между вызовами (тест выше это проверяет).

⚠️ `anthropic.APIError` в `_call_claude` требует импорта `anthropic` даже с FakeClient — импорт внутри функции, пакет уже в deps (Task 1). SDK сам ретраит 429/5xx (`max_retries=1` на клиенте) — это и есть «1 ретрай с бэкоффом» из спеки; наш цикл `for _ in range(2)` ретраит только битую схему.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/ -q`
Expected: все зелёные

- [ ] **Step 5: Commit**

```bash
git add gf/writer.py gf/pricing.py tests/test_writer.py
git commit -m "feat: ядро райтера — write_prompt (Claude forced tool call, лог в prompts/, учёт стоимости)"
```

---

### Task 7: MCP-инструменты и CLI (gf_write_prompt, gf_list_targets)

**Files:**
- Modify: `gf/mcp_server.py`
- Modify: `gf/cli.py`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `writer.write_prompt`, `writer.list_targets`, `writer.WriterError` (Task 6/2).
- Produces:
  - `_write_prompt_impl(project, target, task, refs=None, aspect="", extra="", *, settings, writer=writer_mod) -> dict` — результат `write_prompt` или `{"error": str}` (fail-closed);
  - MCP tools `gf_write_prompt`, `gf_list_targets`; CLI `gf write-prompt`, `gf list-targets`.

- [ ] **Step 1: Write the failing tests** — добавить в `tests/test_mcp.py`:

```python
def test_write_prompt_impl_maps_writer_error(tmp_path):
    from gf.mcp_server import _write_prompt_impl

    class _BoomWriter:
        WriterError = __import__("gf.writer", fromlist=["WriterError"]).WriterError

        def write_prompt(self, *a, **kw):
            raise self.WriterError("нет такой цели")

    out = _write_prompt_impl(str(tmp_path), "magnific/nope", "задача",
                             settings=_settings(tmp_path), writer=_BoomWriter())
    assert out == {"error": "нет такой цели"}


def test_write_prompt_impl_passes_through(tmp_path):
    from gf.mcp_server import _write_prompt_impl

    class _OkWriter:
        WriterError = __import__("gf.writer", fromlist=["WriterError"]).WriterError

        def write_prompt(self, project, target, task, refs=None, aspect=None, extra=None, *, settings):
            return {"prompt": "p", "target": target, "negative": None,
                    "params": None, "notes": None, "log_path": None, "warning": None}

    out = _write_prompt_impl(str(tmp_path), "comfyui/sdxl-test", "задача",
                             settings=_settings(tmp_path), writer=_OkWriter())
    assert out["prompt"] == "p"


def test_writer_tools_registered():
    import asyncio
    from gf.mcp_server import build_server
    mcp, _ = build_server()
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"gf_write_prompt", "gf_list_targets"} <= names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mcp.py -v -k "write_prompt or writer_tools"`
Expected: FAIL — `ImportError: cannot import name '_write_prompt_impl'`

- [ ] **Step 3: Implement.** В `gf/mcp_server.py`:

```python
# импорт вверху, рядом с nano_mod/comfyui_mod:
from . import writer as writer_mod


def _write_prompt_impl(project: str, target: str, task: str, refs: "list | None" = None,
                       aspect: str = "", extra: str = "", *, settings, writer=writer_mod) -> dict:
    try:
        return writer.write_prompt(project, target, task, refs=refs or None,
                                   aspect=aspect or None, extra=extra or None,
                                   settings=settings)
    except writer.WriterError as e:
        return {"error": str(e)}


# в build_server(), после gf_generate_final:
    @mcp.tool()
    def gf_write_prompt(project: str, target: str, task: str, refs: "list | None" = None,
                        aspect: str = "", extra: str = "") -> dict:
        """Написать промпт для цели (target из gf_list_targets) по паспорту модели.
        Работает и для площадок, которые завод не оборачивает (magnific/*)."""
        return _write_prompt_impl(project, target, task, refs, aspect, extra, settings=settings)

    @mcp.tool()
    def gf_list_targets() -> dict:
        """Доступные цели промпт-райтера (из frontmatter'ов паспортов)."""
        try:
            return {"targets": writer_mod.list_targets()}
        except writer_mod.WriterError as e:
            return {"error": str(e)}
```

В `gf/cli.py` (зеркала, паттерн существующих команд):

```python
@app.command("write-prompt")
def write_prompt_cmd(project: str, target: str, task: str,
                     ref: Optional[List[str]] = typer.Option(None, help="референс (повторяемо)"),
                     aspect: str = typer.Option("", help="аспект, напр. 9:16"),
                     extra: str = typer.Option("", help="доп. указания райтеру")):
    """Написать промпт по паспорту цели (живой вызов Claude; нужен ANTHROPIC_API_KEY)."""
    from .core import build_core
    from .mcp_server import _write_prompt_impl
    _echo(_write_prompt_impl(project, target, task, ref or None, aspect, extra,
                             settings=build_core().settings))


@app.command("list-targets")
def list_targets_cmd():
    """Доступные цели промпт-райтера."""
    from .writer import list_targets
    _echo({"targets": list_targets()})
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/ -q`
Expected: все зелёные (`test_writer_tools_registered` теперь видит 14 инструментов)

- [ ] **Step 5: Commit**

```bash
git add gf/mcp_server.py gf/cli.py tests/test_mcp.py
git commit -m "feat: MCP/CLI обвязка райтера — gf_write_prompt, gf_list_targets"
```

---

### Task 8: Авто-путь в gf_generate_draft/final (raw=False, fail-open)

**Files:**
- Modify: `gf/mcp_server.py`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `_write_prompt_impl`-паттерн, `writer.WriterError`, `Settings.writer_draft_target`/`writer_final_target`.
- Produces: `_generate_draft_impl(..., raw: bool = False, writer=writer_mod)` и `_generate_final_impl(..., raw: bool = False, writer=writer_mod)`; в ответе новые ключи `prompt_used: str`, `prompt_log: str|None`, `writer_skipped: str|None`. MCP-сигнатуры `gf_generate_draft(..., raw: bool = False)`, `gf_generate_final(..., raw: bool = False)`; имя параметра `prompt` не меняется.

- [ ] **Step 1: Write the failing tests** — добавить в `tests/test_mcp.py`:

```python
class _OkAutoWriter:
    from gf.writer import WriterError  # class attr, чтобы except writer.WriterError работал

    def __init__(self):
        self.calls = []

    def write_prompt(self, project, target, task, refs=None, aspect=None, extra=None, *, settings):
        self.calls.append(target)
        return {"prompt": "REWRITTEN", "negative": "auto-neg", "params": {"steps": 50},
                "notes": None, "target": target, "log_path": "/tmp/log.md", "warning": None}


class _FailAutoWriter:
    from gf.writer import WriterError

    def write_prompt(self, *a, **kw):
        raise self.WriterError("ключ протух")


def test_draft_raw_true_bypasses_writer(tmp_path):
    w = _OkAutoWriter()
    out = _generate_draft_impl(str(tmp_path), "as is", 1, "", 0, raw=True,
                               settings=_settings(tmp_path), comfy=_FakeComfy(), writer=w)
    assert w.calls == []
    assert out["prompt_used"] == "as is"
    assert out["writer_skipped"] is None


def test_draft_auto_rewrites_and_reports(tmp_path):
    w = _OkAutoWriter()
    out = _generate_draft_impl(str(tmp_path), "задача", 1, "", 0,
                               settings=_settings(tmp_path), comfy=_FakeComfy(), writer=w)
    assert w.calls == ["comfyui/sdxl-juggernaut"]
    assert out["prompt_used"] == "REWRITTEN"
    assert out["prompt_log"] == "/tmp/log.md"


def test_draft_explicit_negative_wins(tmp_path):
    captured = {}

    class _Comfy(_FakeComfy):
        def generate(self, prompt, out_dir, **kw):
            captured.update(kw, prompt=prompt)
            return super().generate(prompt, out_dir, **kw)

    _generate_draft_impl(str(tmp_path), "задача", 1, "my-neg", 0,
                         settings=_settings(tmp_path), comfy=_Comfy(), writer=_OkAutoWriter())
    assert captured["prompt"] == "REWRITTEN"
    assert captured["negative"] == "my-neg"  # явный негатив главнее авто


def test_draft_writer_failure_falls_open(tmp_path):
    out = _generate_draft_impl(str(tmp_path), "задача", 1, "", 0,
                               settings=_settings(tmp_path), comfy=_FakeComfy(),
                               writer=_FailAutoWriter())
    assert out["writer_skipped"] == "ключ протух"
    assert out["prompt_used"] == "задача"     # генерация прошла сырым текстом
    assert len(out["images"]) == 1


def test_final_auto_uses_final_target(tmp_path):
    w = _OkAutoWriter()
    out = _generate_final_impl(str(tmp_path), "задача", [], "9:16",
                               settings=_settings(tmp_path), nano=_FakeNano(), writer=w)
    assert w.calls == ["nano/gemini-image"]
    assert out["prompt_used"] == "REWRITTEN"
```

Также обновить два существующих теста, которые зовут `_generate_draft_impl`/`_generate_final_impl` без райтера (`test_draft_impl_generates_and_is_free`, `test_final_impl_generates_and_logs_cost`, `test_final_impl_blocked_by_cap`): передать `raw=True` — их предмет не райтер. (`_settings` уже с `writer_enabled=False` из Task 1 — но `raw=True` делает намерение явным.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mcp.py -v`
Expected: FAIL — `TypeError: _generate_draft_impl() got an unexpected keyword argument 'raw'`

- [ ] **Step 3: Implement.** В `gf/mcp_server.py` — общий хелпер + правки обоих impl:

```python
def _maybe_rewrite(project, task, negative, target, *, settings, writer):
    """Авто-путь: fail-open. Возвращает (prompt, negative, prompt_log, writer_skipped)."""
    try:
        res = writer.write_prompt(project, target, task, settings=settings)
    except writer.WriterError as e:
        return task, negative, None, str(e)
    return res["prompt"], (negative or res.get("negative") or ""), res.get("log_path"), None


def _generate_draft_impl(project: str, prompt: str, n: int = 4, negative: str = "",
                         seed: int = 0, raw: bool = False, *, settings,
                         comfy=comfyui_mod, budget=budget_mod, writer=writer_mod) -> dict:
    prompt_used, neg_used, prompt_log, skipped = prompt, negative, None, None
    if not raw:
        prompt_used, neg_used, prompt_log, skipped = _maybe_rewrite(
            project, prompt, negative, settings.writer_draft_target,
            settings=settings, writer=writer)
    project_dir = Path(project)
    date = media.today()
    out_dir = media.drafts_dir(project_dir, date)
    cost = pricing.estimate("comfyui", n)
    gate = budget.check(project_dir, cost, settings.image_cap_usd)
    if not gate["allowed"]:
        return {"error": gate["reason"], "images": [], "backend": "comfyui",
                "cost_usd": cost, "spent_usd": gate["spent"]}
    saved = comfy.generate(prompt_used, out_dir, server_url=settings.comfyui_url,
                           ckpt=settings.comfyui_ckpt, workflow_path=settings.comfyui_workflow or None,
                           n=n, negative=neg_used, seed=seed)
    budget.log_cost(project_dir, "comfyui", n, cost, note=f"draft {date}")
    return {"images": [str(p) for p in saved], "backend": "comfyui",
            "cost_usd": cost, "spent_usd": budget.spent(project_dir),
            "prompt_used": prompt_used, "prompt_log": prompt_log, "writer_skipped": skipped}
```

`_generate_final_impl` — симметрично: параметр `raw: bool = False` после `aspect`, `writer=writer_mod` в kwargs, `_maybe_rewrite(..., settings.writer_final_target, ...)`, negative у финала нет — хелпер вызвать с `negative=""` и результат негатива игнорировать; те же три ключа в ответе. MCP-декораторы:

```python
    @mcp.tool()
    def gf_generate_draft(project: str, prompt: str, n: int = 4,
                          negative: str = "", seed: int = 0, raw: bool = False) -> dict:
        """Generate N cheap ComfyUI drafts. prompt = задача (райтер перепишет);
        raw=True — текст уходит в модель дословно."""
        return _generate_draft_impl(project, prompt, n, negative, seed, raw, settings=settings)

    @mcp.tool()
    def gf_generate_final(project: str, prompt: str, refs: "list | None" = None,
                          aspect: str = "9:16", raw: bool = False) -> dict:
        """Generate a client-facing final with Nano Banana. prompt = задача (райтер перепишет);
        raw=True — дословно."""
        return _generate_final_impl(project, prompt, refs, aspect, raw, settings=settings)
```

CLI `generate-draft`/`generate-final`: добавить `raw: bool = typer.Option(False, help="не переписывать промпт райтером")` и пробросить.

⚠️ Fail-open ловит только `writer.WriterError` — прочие исключения (баг в коде) должны падать, это честнее для отладки. `_maybe_rewrite` вызывается ДО budget gate: стоимость райтера центовая и не гейтится (по спеке), а его лог пишется внутри `write_prompt`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/ -q`
Expected: все зелёные

- [ ] **Step 5: Commit**

```bash
git add gf/mcp_server.py gf/cli.py tests/test_mcp.py
git commit -m "feat: авто-путь райтера в gf_generate_* (raw=False, fail-open с writer_skipped)"
```

---

### Task 9: Живой смоук, Hermes, доки

**Files:**
- Modify: `docs/ТЗ.md`, `docs/АРХИТЕКТУРА.md`, `docs/ЗАДАЧНИК.md`
- Modify: `.env` (не в git) — `ANTHROPIC_API_KEY`

**Interfaces:**
- Consumes: всё выше.

- [ ] **Step 1: Живой смоук CLI** (нужен `ANTHROPIC_API_KEY` в `.env` завода — попросить у Кира, если нет):

Run: `python -m gf.cli list-targets`
Expected: JSON со всеми целями из promptdocs.

Run: `python -m gf.cli write-prompt <тестовый-проект> comfyui/sdxl-juggernaut "Тестовый кадр: женщина у окна, дождь" --aspect 9:16`
Expected: JSON с `prompt` (английский, теговый стиль по паспорту), `log_path` указывает на созданный файл в `<проект>/prompts/`.

- [ ] **Step 2: Опционально — сквозной смоук с живым ComfyUI** (если ComfyUI поднят): `python -m gf.cli generate-draft <тестовый-проект> "женщина у окна, дождь" --n 1` → в ответе `prompt_used` ≠ исходной задаче, `writer_skipped: null`, картинка на диске.

- [ ] **Step 3: Рестарт Hermes gateway** — новые инструменты подхватятся при discovery на старте (см. память hermes-integration: discovery один раз при старте; `/reload-mcp` только в TUI). Проверить в `agent.log`: `MCP server 'generation_factory' (stdio): registered 16 tool(s)` (12 + gf_write_prompt, gf_list_targets — 14 + 2 служебных уже в счёте; итог сверить по факту). ⚠️ Ключ ANTHROPIC_API_KEY должен быть виден процессу gateway (он в `.env` завода — `load_dotenv()` подхватит из cwd репо; проверить, что stdio-запись в config.yaml запускается с рабочей директорией репо, иначе прописать ключ в env запуска).

- [ ] **Step 4: Обновить доки:**
  - `ТЗ.md`: раздел про промпт-слой (инструменты, цели, паспорта);
  - `АРХИТЕКТУРА.md`: §промпт-слой + в §8 «осознанные отступления» — promptdocs внутри пакета `gf/`, а не в корне репо (packaging);
  - `ЗАДАЧНИК.md`: закрыть пункт 3 (инструменты Magnific проверены: есть t2i + upscale), добавить открытые хвосты (vision-режим райтера, style.md — кто заполняет).

- [ ] **Step 5: Финальная проверка и коммит**

Run: `python -m pytest tests/ -q`
Expected: все зелёные

```bash
git add docs/
git commit -m "docs: промпт-слой в ТЗ/АРХИТЕКТУРА/ЗАДАЧНИК; Magnific: t2i+upscale подтверждены"
```

---

## Self-review (выполнен)

- **Покрытие спеки:** паспорта+исследование (T3-T5), райтер (T2, T6), конфиг (T1), MCP/CLI (T7), авто-путь fail-open (T8), лог prompts/ и учёт стоимости (T6), смоук+Hermes+доки (T9). Ошибочная матрица спеки: unknown target/битый frontmatter (T2), нет ключа/выключен (T6: `_make_client`/`writer_enabled`), API-ошибка → ретрай SDK → WriterError (T6), битая схема → 1 ретрай (T6), style.md отсутствует — не ошибка (T6 `load_style`), лог не записался → warning (T6), fail-open с флагом (T8). ✅
- **Типы согласованы:** `write_prompt` возвращает dict с `prompt/negative/params/notes/target/log_path/warning` — T7 и T8 читают ровно эти ключи; `writer=` инжектится объектом с `write_prompt` и атрибутом `WriterError`. ✅
- **Отступление от спеки одно** (promptdocs внутри `gf/`), зафиксировано в Global Constraints и в T9-доках. ✅
