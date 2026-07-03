# Content Factory (generation-factory) — Design Spec

**Date:** 2026-07-03
**Status:** Approved (brainstorm)
**Scope:** Новый проект `R:\Dev\tools\content-factory` — генеративный слой (ComfyUI/Nano Banana/Magnific) для Hermes через отдельный MCP-сервер. Работает по новой структуре хранения (spec `2026-07-03-knowledge-base-storage-structure-design.md`). Заменяет громоздкого агента `Q:\Lion Films. AI studio`, переиспользуя из него только генеративный код.

## Goal

Дать Hermes способность вести генеративный препрод по проекту: разложить бриф на референсы-кирпичи, создавать переиспользуемые building-blocks (локации, персонажи), собирать кадры раскадровки (лицо+локация), хранить промпты, собирать контакт-листы — просто, без старой машинерии (scaffold/lint/реестры-гейты/iter-gating/QA-promotion/9 агентов).

## Context / решение

- Старый агент `Q:\Lion Films. AI studio` (`github.com/Znen/Lion_Films_AI`) — зрелый lifecycle-фреймворк (Claude Code + ~20 Python-модулей + 9 агентов), но его ценность для пользователя — **только генерация**; машинерия (`00_brief..05_review`, `reference_register`/`shot_registry`/`return.json`-гейты, `lint`, QA-promotion) избыточна и противоречит принципу «одна папка = один проект, просто».
- Решение (путь B): **новый чистый проект** `content-factory`, забираем из старого только генеративный код (`tools/nitro_banana/nitro_generate.py` = Nano Banana, `tools/comfyui-mcp` / ComfyUI-роутер, при нужде `tools/imagegen/run.py`, cost-gating `tools/common/budget.py`+`pricing.py`). Старый проект **архивируем** (не удаляем — там реальные данные: 322 мастера Delicados, 22 итерации AIPriest).
- **Всё работает через Hermes** — генерация даётся как MCP-инструменты (рядом с уже подключёнными knowledge-factory и magnific).

## Архитектура

- **`generation-factory` — отдельный MCP-сервер** (Python, паттерн knowledge-factory: FastMCP, stdio+HTTP). Подключается к Hermes третьим MCP.
- **Backends:**
  - **ComfyUI** (локально, RTX 4070) — массовые дешёвые черновики невысокого качества (нащупать направление).
  - **Nano Banana** (локальный Express/Gemini-сервер из старого агента) — основной финал, уходит клиенту; multi-image референсы.
  - **Magnific** — альтернативный финал; у Hermes уже подключён как MCP (Hermes зовёт напрямую, gf его не оборачивает).
- Поток: *ComfyUI (наброски) → выбор → Nano Banana / Magnific (финал с референсами) → `media/generated/<дата>/`*.

## Структура медиа проекта (по storage-spec)

```
<project>/media/
├── references/          ← ВХОДЯЩЕЕ из брифа (сырьё)
│   ├── characters/          лицо актрисы, персонажи
│   ├── locations/           референс локации (кухня от агентства)
│   └── look-and-feel/       общий стиль, интерьер/экстерьер настроение
├── locations/           ← СОЗДАННЫЕ кирпичи-локации (переиспользуемые, весь проект)
│   └── <name>/              выбранные ракурсы (напр. kitchen/)
├── characters/          ← утверждённые персонажи (лицо + удачные генерации)
│   └── <name>/
├── generated/           ← КАДРЫ-сборки, датированные
│   └── <YYYY-MM-DD>/
│       └── shot-XX/
│           ├── iter-01.png, iter-02.png…
│           └── prompts/iter-01.json…   (промпт+backend+референсы+seed; связь по имени)
└── storyboards/         ← раскадровка (от руки — референс композиции)
```

**Continuity — через building-blocks, не авто-реестр:** локации и персонажи создаются один раз и переиспользуются. «Тот же персонаж в новой локации» = то же лицо из `characters/<name>/` + другая готовая `locations/<name>/`.

## MCP-инструменты (для Hermes)

| Инструмент | Что делает |
|---|---|
| `gf_generate_draft(project, prompt, refs[], n)` | ComfyUI: N дешёвых черновиков → временная папка/`generated/<date>/_drafts/` |
| `gf_generate_final(project, prompt, refs[], backend=nano)` | Nano Banana (или magnific через Hermes): финал с multi-референсами |
| `gf_save_asset(project, image, kind=location\|character, name)` | сохранить выбранное в кирпич (`locations/<name>/` или `characters/<name>/`) |
| `gf_assemble_shot(project, shot, character, location, prompt, date)` | сборка кадра (лицо+локация multi-ref) → `generated/<date>/shot-XX/iter-*`, промпт в `prompts/` |
| `gf_contact_sheet(project, selection)` | контакт-лист ПО ЗАПРОСУ (за дату / последние N / явный список) — НЕ авто |

Декомпозицию агентского брифа на референсы Hermes делает сам (читает бриф + раскладывает по `references/*` своими file-инструментами; удобнее станет с будущим `kf_add_file`).

## Workflow

1. Пришёл агентский бриф (по ссылке) → Hermes раскладывает: лицо→`references/characters/`, локация-референс→`references/locations/`, look&feel→`references/look-and-feel/`, раскадровка→`storyboards/`, сценарий→`docs/`.
2. «Создай кухню» → `gf_generate_draft` (ракурсы через ComfyUI) → выбор → `gf_save_asset(location, kitchen)`.
3. «Собери кадр 1» → `gf_assemble_shot(character=actress, location=kitchen)` → финал в `generated/<date>/shot-01/` + промпт в `prompts/`.
4. Работа по кадрам по очереди; continuity — переиспользование кирпичей.
5. «Контакт-лист за сегодня» → `gf_contact_sheet`.

## Промпты / память процесса

- Промпты хранятся `generated/<date>/shot-XX/prompts/iter-*.json` (промпт + backend + референсы + seed + дата). Отделены от картинок, связь по имени.
- Назначение: (а) отдать клиенту по запросу; (б) анализ — воспроизвести похожее / избежать неудачного.
- Память «что сработало на кадре N→N+1»: Hermes перед новым кадром читает `prompts/` прошлых удачных кадров проекта и переносит удачные подходы.

## Cost-gating (переносим)

`tools/common/budget.py` + `pricing.py` из старого агента (не завязаны на структуру) — переносим, чтобы генерация уважала бюджет.

## Не-цели / сознательно выбрасываем

- Старая структура `00_brief..05_review`, `.lf_project`, `scaffold`/`lint`.
- Реестры-гейты: `reference_register.json`, `shot_registry.json` (base-gate sha256), `return.json` (iteration-gating), QA-promotion в `library/wins/`.
- 9 постоянных агентов (Producer/Quality-Gatekeeper/…), двухуровневая агентура — вместо неё оркестрирует сам Hermes.
- Автосборка контакт-листа (только по запросу).
- Symlink `projects_live`/`WORK` (упраздняется отдельной фазой storage-spec).

## Открытые детали (уточнить при реализации / в плане)

- Как режем кадры раскадровки: вероятно по команде пользователя («кадр N»), не авто-нарезка изображения.
- Как Hermes забирает агентский бриф по ссылке (скачивание → inbox → раскладка).
- Точный ComfyUI REST API (`/prompt`, workflow-json) и локальный порт; вызов Nano-сервера (endpoint из `nitro_generate.py`).
- Механизм multi-референса в Nano/Magnific (сколько входных изображений, как передаётся лицо+локация).
- Транспорт MCP (stdio для локального Hermes; HTTP+bearer как у kf, если понадобится).

## Реализация — фазы

- **Ф1** — скелет проекта `content-factory` (git, pyproject, MCP-сервер), перенос генеративного кода (nitro_generate, ComfyUI-роутер, budget/pricing) из старого агента, инструмент `gf_generate_final` (Nano) + `gf_generate_draft` (ComfyUI) — минимальная генерация через Hermes.
- **Ф2** — building-blocks: `gf_save_asset`, `gf_assemble_shot` (multi-ref сборка кадра), датированная структура, промпты.
- **Ф3** — `gf_contact_sheet`, память процесса (чтение прошлых промптов).
- **Ф4** — подключение к Hermes (config.yaml mcp_servers), архивация старого `Lion Films. AI studio`.
- Зависит от готовности storage-Фазы 2 (упразднение WORK) — не блокирующе, но желательно.
