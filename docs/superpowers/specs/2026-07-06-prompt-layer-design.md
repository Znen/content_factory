# Промпт-слой (prompt writer) — дизайн

**Date:** 2026-07-06
**Status:** Approved (brainstorm)
**Scope:** Новый слой внутри `content-factory`: отдельный агент-райтер пишет промпты для генеративных моделей (ComfyUI/SDXL, Nano/Gemini, Magnific/Freepik) на основе паспортов моделей. Причина: Hermes (deepseek) пишет плохие промпты — не знает синтаксис моделей, пишет слабо, теряет контекст брифа.

## Решения брейншторма

| Вопрос | Решение |
|---|---|
| Что лечим | Всё вместе: незнание синтаксиса + слабый текст + потеря контекста брифа |
| LLM-райтер | Claude API (модель конфигурируема, default `claude-sonnet-5`) |
| Знания о моделях | Markdown-паспорта в репо завода (`promptdocs/`), версионируются в git |
| Интерфейс | Отдельный `gf_write_prompt` (работает и для Magnific) + авто-переписывание внутри `gf_generate_draft/final` |
| Контекст проекта | `<project>/prompts/style.md` (редактируемый style-файл) + аргументы вызова |
| Охват v1 | Все три площадки; Magnific: рабочий набор (3–5 моделей) глубоко + короткий справочник по каталогу |
| Архитектура райтера | Подход A: однопроходный (один вызов Claude, контекст собирает код), без agent loop; vision-задел на потом |
| Источники паспортов | Дистилляция готовых скилов экосистемы + собственное исследование Magnific/Freepik |

Отклонено: агентный райтер с tool use (сложность/цена без доказанной нужды — вернёмся, если качество упрётся), «только знания без LLM» (deepseek слаб и с гайдами), полный глубокий охват каталога Magnific (устареет раньше, чем пригодится).

### Найденные готовые скилы (источники для дистилляции)

- `replicate/skills@prompt-images` — общий image-промптинг;
- `mckruz/comfyui-expert@comfyui-prompt-engineer` (+ соседние comfyui-* того же автора) — ComfyUI/SD;
- `everyinc/compound-engineering-plugin@ce-gemini-imagegen`, `johnlindquist/claude@gemini-image` — Gemini (Nano);
- `agentspace-so/runcomfy-agent-skills@flux-kontext` и аналоги — Flux (если возьмём на Magnific);
- `justinperea/midjourney-cc-skill@midjourney-prompt-engineering` — переносимые общие принципы.

Под Magnific/Freepik-платформу готовых скилов нет — исследуем сами (живой `images_models_list`/`video_models_list` + веб-доки Freepik).

## Архитектура

```
Hermes ──► gf_write_prompt(project, target, task, refs?) ─┐
                                                          │
              ┌───────────── gf/writer.py ◄───────────────┘
              │  1. паспорт цели   promptdocs/<target>.md
              │  2. стиль проекта  <project>/prompts/style.md
              │  3. задача + рефы  из аргументов
              │        ↓
              │  один вызов Claude API (forced tool call)
              │        ↓
              │  {prompt, negative, params, notes}
              │        ↓
              │  лог в <project>/prompts/<date>-<slug>-NN.md
              └──► ответ Hermes'у
```

Три способа использования:
1. **Явный** — `gf_write_prompt(target="magnific/mystic", ...)`: Hermes получает промпт и сам зовёт Magnific напрямую. Слой покрывает площадки, которые завод не оборачивает.
2. **Автоматический** — `gf_generate_draft/final(…, raw=False)`: задача прогоняется через райтера перед бэкендом; Hermes «не может забыть» позвать райтера.
3. **Справочный** — `gf_list_targets()`: допустимые цели из frontmatter'ов паспортов.

Райтер — чистая функция с одним LLM-вызовом; весь контекст собирает детерминированный код завода.

## Компоненты

### `gf/writer.py` (новый)

- `write_prompt(project, target, task, refs=None, aspect=None, extra=None, *, settings, client=None) -> dict` — сборка контекста → вызов Claude → `{"prompt", "negative", "params", "notes", "target", "log_path"}`. `client=None` → создаётся из настроек; в тестах инжектится мок (паттерн `session=requests` из comfyui.py).
- `load_passport(target) -> str` — читает `promptdocs/<target>.md`; нет паспорта → ошибка со списком доступных целей.
- `load_style(project) -> str | None` — `<project>/prompts/style.md`; отсутствие — не ошибка.
- `log_prompt(project, target, task, result) -> Path` — markdown в `<project>/prompts/YYYY-MM-DD-<slug>-NN.md`, где slug = последний сегмент цели (`magnific/mystic` → `mystic`); нумерация — паттерн `media.next_index`.

### `promptdocs/` (новый, в корне репо рядом с `workflows/`)

Паспорт = markdown с YAML-frontmatter:

```markdown
---
target: comfyui/sdxl-juggernaut
platform: comfyui
syntax: tags            # tags | natural | hybrid
max_len: 300            # ориентир в токенах
negative: true
refs: none              # none | single | multi(N)
sources: [mckruz/comfyui-expert@comfyui-prompt-engineer]
updated: 2026-07-06
---
# Как писать промпт для <target>
<структура идеального промпта, порядок блоков, веса, типовые фейлы,
3–5 примеров «задача → плохо → хорошо»>
```

Состав v1: `comfyui/sdxl-juggernaut.md`, `nano/gemini-image.md`, `magnific/<3–5 моделей>.md`, `magnific/_catalog.md` (справочник «когда какую модель брать»). Frontmatter машиночитаемый: `gf_list_targets` строит список из него; тело вставляется в system prompt райтера.

### Конфиг (`gf/config.py`, паттерн env)

- `GF_WRITER_MODEL` (default `claude-sonnet-5`), `GF_WRITER_MAX_TOKENS` (default 2000);
- ключ — стандартный `ANTHROPIC_API_KEY` (env/`.env`);
- `GF_WRITER_ENABLED` (default true): выключен → явный вызов возвращает ошибку с объяснением, авто-путь тихо пропускает райтера.

### MCP-инструменты (`gf/mcp_server.py`)

- `gf_write_prompt(project, target, task, refs=[], aspect="", extra="")` — новый;
- `gf_list_targets()` — новый;
- `gf_generate_draft(..., raw=False)`, `gf_generate_final(..., raw=False)` — изменение: при `raw=False` текст трактуется как задача и идёт через райтера (draft → comfyui-паспорт, final → nano-паспорт); `raw=True` — старое поведение (текст дословно в модель). Имя параметра `prompt` не меняется (совместимость), меняется только трактовка.

CLI-зеркала: `gf write-prompt`, `gf list-targets`.

### Зависимость

`anthropic` SDK. При имплементации свериться с claude-api skill по актуальным параметрам API.

## Поток данных

**Явный вызов:**
1. Валидация цели (нет паспорта → ошибка со списком).
2. Сборка контекста (без LLM): system = роль + тело паспорта + контракт вывода; user = блоки `Задача`, `Стиль проекта` (если есть), `Референсы` (имена файлов + пометки; v1 — без самих картинок), `Аспект/доп. указания`.
3. Вызов Claude: один запрос, forced tool call `emit_prompt` со схемой `{"prompt": str, "negative": str|null, "params": obj|null, "notes": str|null}`. `params` — рекомендации под площадку; `notes` — короткое «почему так».
4. Учёт: стоимость из usage-токенов → `budget.log_cost(project, "writer", ...)`. Не гейтится через `image_cap_usd` (центы), но видна в `spent`.
5. Лог в `<project>/prompts/` (провенанс: из чего родилась картинка).
6. Ответ: весь структурированный результат + `log_path`.

**Авто-путь** (`gf_generate_*`, `raw=False`):
1. Внутри — тот же `write_prompt` с целью бэкенда.
2. Берутся `prompt` и `negative` (явный `negative` от Hermes главнее). Числовые `params` в v1 не применяются — только логируются как рекомендация; steps/cfg управляются явными аргументами.
3. Дальше существующий поток (budget gate → backend → сохранение). В ответе `prompt_used` + `prompt_log`.
4. `raw=True` — короткое замыкание, райтер не вызывается.

Итерация «не понравилось → поправь»: отдельного механизма нет; Hermes зовёт `gf_write_prompt` снова, передав в `extra` правку и прошлый промпт из лога.

## Обработка ошибок

Принцип: **явный путь — fail-closed, авто-путь — fail-open с флагом** (промпт-слой не останавливает фабрику).

| Ситуация | Явный `gf_write_prompt` | Авто-путь |
|---|---|---|
| Нет ключа / райтер выключен | `{"error": …}` с инструкцией | Генерация с текстом как есть + `writer_skipped: "<причина>"` |
| API-ошибка (429/5xx/таймаут) | 1 ретрай с бэкоффом → ошибка | 1 ретрай → fallback на сырой текст + флаг |
| Неизвестный `target` | Ошибка + список целей | Не бывает (цель зашита за бэкендом) |
| Битый frontmatter паспорта | Ошибка с путём к файлу | То же (ошибка конфигурации завода) |
| `style.md` нет/нечитаем | Не ошибка; пометка в `notes` | То же |
| Ответ не прошёл валидацию схемы | 1 ретрай → ошибка | 1 ретрай → fallback + флаг |
| Не записался лог | Результат возвращается + `warning` | То же |

## Тестирование

Паттерн завода: pytest, без живых API, инжектируемые зависимости (`client=`).

- `test_writer.py`: паспорта (найден/нет/список; парс frontmatter; «все файлы `promptdocs/` имеют валидный frontmatter с обязательными ключами»); сборка контекста (style есть/нет, рефы, extra); `write_prompt` с FakeClient (маппинг ответа, ретрай на битой схеме, ошибки API); нумерация/содержимое лога; учёт стоимости из usage.
- `test_mcp_generate.py` (расширение): `raw=True` — райтер не тронут; `raw=False` — `prompt_used` из фейк-райтера, приоритет явного `negative`, `writer_skipped` при выключенном райтере/ошибке; `params` не применяются к бэкенду.
- Живой смоук — вручную через CLI: `gf write-prompt <project> comfyui/sdxl-juggernaut "задача"`.

Качество паспортов тестами не ловится: проверяется ревью в фазе исследования и практикой (лог `prompts/` — материал для правок; паспорта в git — правки дёшевы).

## Фазы внедрения

- **Ф-П1. Исследование** — установить/прочитать найденные скилы, дистиллировать в паспорта; живой каталог Magnific (`images_models_list`/`video_models_list`) + веб-доки Freepik → 3–5 паспортов Magnific + `_catalog.md`; ревью Киром.
- **Ф-П2. Райтер** — `writer.py` + конфиг + тесты.
- **Ф-П3. Обвязка** — MCP-инструменты, авто-путь, CLI, живой смоук, рестарт Hermes-gateway.

## Открытые вопросы (не блокируют v1)

- Vision-режим: передавать райтеру сами картинки-референсы (для Nano/Magnific multi-ref) — интерфейс уже допускает (`refs`), добавится малым шагом, если качество упрётся.
- Выбор конкретных 3–5 моделей Magnific — по живому каталогу в Ф-П1.
- `style.md`: кто заполняет первым (Кир руками или Hermes по брифу) — решится при принятии Рябы.
