# Задача: Magnific как бэкенд завода (`content-factory`)

**Дата:** 2026-07-06
**Статус:** дизайн одобрен (брейншторм с Киром), готов к реализации
**Исполнитель:** Claude Code в терминале
**Тип:** новая фича — третий генеративный бэкенд рядом с ComfyUI и Nano

---

## 0. Для исполнителя — прочитай первым

Ты добавляешь в завод `content-factory` **третий бэкенд** — Magnific (платформа Freepik) —
чтобы завод сам ходил к Magnific по HTTP, писал промпт через существующий промпт-слой,
прикладывал референсы, дожидался результата и складывал картинку в хранилище проекта.

**С чего начать (обязательный порядок):**

1. Прочитай существующий код и повтори его паттерны — НЕ изобретай свой стиль:
   - `gf/backends/nano.py` — образец HTTP-бэкенда (инжектируемый `session`, свои исключения,
     аккуратная обработка сетевых ошибок). Твой `magnific.py` строится по этому шаблону.
   - `gf/backends/comfyui.py` — второй пример бэкенда.
   - `gf/mcp_server.py` — как инструменты обёрнуты, как работает `_maybe_rewrite` (fail-open
     авто-путь через райтера), как `gf_generate_final` устроен end-to-end. **Твой инструмент
     `gf_generate_magnific` — это клон `gf_generate_final` с другим бэкендом и обязательным `model`.**
   - `gf/writer.py` — промпт-слой. **Его НЕ меняешь.** Просто передаёшь `target=f"magnific/{model}"`.
   - `gf/config.py`, `gf/pricing.py`, `gf/budget.py`, `gf/media.py` — точки, куда добавляешь мелочи.
   - `gf/promptdocs/magnific/` — паспорта моделей УЖЕ написаны (`mystic.md`,
     `seedream-v4-5-edit.md`, `flux-kontext-pro.md`, `kling-v2-5-pro.md`) + `_catalog.md`.
   - `docs/superpowers/specs/2026-07-06-prompt-layer-design.md` — как устроен промпт-слой.
   - `gf/promptdocs/magnific/_catalog.md` — **важные предупреждения площадки** (upload-флоу,
     кредиты, circuit-breaker). Прочитай целиком.

2. **СНАЧАЛА подтверди REST API Freepik (см. раздел 3) — это главный риск.** Точные эндпоинты,
   имена полей и формат ответов у нас НЕ подтверждены. Не выдумывай URL. Если живого доступа
   к докам/ключу нет — остановись и спроси Кира, а не пиши код против воображаемого API.

3. Следуй процессу проекта: **TDD, тесты без живых API (инжектируемый `session`/`client`),
   fail-closed на явном пути, fail-open на авто-пути.** Разбивка на маленькие модули с ясной
   границей.

**Язык:** комментарии и docstrings — по-русски (как в существующем коде завода), идентификаторы
и промпты — по-английски.

---

## 1. Контекст: что за завод

`content-factory` (пакет `gf`) — генеративный MCP-слой для агента Hermes (DeepSeek).
Hermes даёт заводу задачу на естественном языке, завод генерирует картинки и складывает их
в `<project>/media/generated/<date>/` по storage-спеке.

**Существующие бэкенды:**
- **ComfyUI** (`gf_generate_draft`) — дешёвые локальные черновики, $0.00.
- **Nano Banana / Gemini** (`gf_generate_final`) — финалы через локальный сервер Nitro.
  **Сейчас заблокирован (Gemini-403)** — одна из причин, зачем нужен Magnific.

**Промпт-слой** (`gf/writer.py` + `promptdocs/`): один вызов Claude API превращает сырую
задачу Hermes в грамотный промпт по «паспорту» модели. Работает для любого `target`, у которого
есть паспорт. Вызывается автоматически внутри `gf_generate_*` при `raw=False` (дефолт).

**Бюджет** (`gf/budget.py`): пишет стоимость каждой генерации в `<project>/media/.gf_cost_log.jsonl`,
опционально гейтит по `GF_IMAGE_CAP_USD`.

---

## 2. Что строим (одним абзацем)

Новый инструмент **`gf_generate_magnific(project, model, prompt, refs=[], aspect="", raw=False)`**
и новый модуль **`gf/backends/magnific.py`** — HTTP-клиент к Freepik/Magnific REST API.
Поток: Hermes → (райтер пишет промпт по паспорту `magnific/<model>`) → залить локальные референсы
во внешнее хранилище → POST задачу → дождаться (поллинг) → скачать картинку в `media/` →
записать стоимость и провенанс → вернуть Hermes'у готовый путь.
Всё остальное (райтер, бюджет, media, курация) переиспользуется без изменений.

---

## 3. КРИТИЧНО: сначала подтверди REST API Freepik

Наш `_catalog.md` собирался по веб-докам; **точные REST-детали не проверены**. Прежде чем писать
`backends/magnific.py`, подтверди по живой документации Freepik (`docs.freepik.com` /
`api.freepik.com`) ЛИБО спроси Кира:

- [ ] Base URL и версия API (`https://api.freepik.com/v1/...`?).
- [ ] Аутентификация: заголовок с API-ключом (`x-freepik-api-key`? `Authorization`?).
- [ ] Эндпоинт(ы) генерации per-model: как выбирается модель — путём (`/v1/ai/mystic`) или
      полем в теле? Как передаются `prompt`, `aspect`, `refs`?
- [ ] **Upload-флоу референсов** — как локальный файл превращается в http-URL, который примет
      генерация. (В облачном MCP это `creations_request_upload` → `PUT` → `creations_finalize_upload`;
      в REST — подтвердить реальные эндпоинты.)
- [ ] **Асинхронность**: POST возвращает `task_id`? Как поллить статус (GET по task_id)?
      Какие статусы (`IN_PROGRESS`/`COMPLETED`/`FAILED`)? Где в ответе URL готовой картинки?
- [ ] Коды ошибок: невалидный ключ, недостаточно кредитов, невалидные параметры, rate-limit.

**Если доступа к докам/ключу нет — не пиши код против догадок. Остановись и спроси Кира.**
Зафиксируй подтверждённые факты в комментарии вверху `backends/magnific.py`, чтобы следующий
человек не гадал.

---

## 4. Решения брейншторма (не пересматривать без Кира)

| Развилка | Решение | Отклонено |
|---|---|---|
| Транспорт | **REST API Freepik** (HTTP-клиент, как `nano.py`) | облачный MCP-в-MCP |
| Охват v1 | **только генерация картинок**: выбор модели + промпт + референсы + скачивание | video (Kling), upscale, отдельная edit-линия |
| Форма инструмента | **отдельный `gf_generate_magnific`**, `model` — обязательный явный параметр | вливать в `gf_generate_final` |
| Стоимость | **плоская таблица per-model** в `pricing.py` | `simulate_cost`, гибрид |
| Ожидание результата | **завод ждёт сам** (sync + внутренний поллинг, таймаут → вернуть `task_id` + флаг) | Hermes поллит по task_id |
| Промпт | как везде: `raw=False` → через райтера; `raw=True` → дословно | — |

**Модели v1** (у них уже есть паспорта, это t2i/edit — картинки):
`mystic`, `seedream-v4-5-edit`, `flux-kontext-pro`. Модель `kling-v2-5-pro` — видео, **вне v1**.
`model` маппится в цель райтера как `target = f"magnific/{model}"`.

---

## 5. Компоненты

### 5.1. `gf/backends/magnific.py` (новый) — HTTP-клиент

Строй по образцу `nano.py`: чистые функции, инжектируемый `session` (дефолт `requests`),
свои исключения, никакой связи с бюджетом/проектом (это забота вызывающего в `mcp_server.py`).

Примерная поверхность (уточни по факту API из раздела 3):

```python
class MagnificError(Exception): ...

def upload_reference(session, base_url, api_key, path: Path) -> str:
    """Локальный файл → публичный http(s)-URL (request-upload → PUT → finalize).
    Возвращает URL, пригодный как референс в generate()."""

def generate(prompt: str, refs: "list[Path]", out_dir: Path, *,
             model: str, base_url: str, api_key: str,
             aspect: str = "", timeout: int = 180, poll_interval: int = 3,
             session=None) -> "dict":
    """Полный цикл: залить рефы → POST задачу → поллить до готовности → скачать картинку.
    Возвращает {"images": [Path, ...], "task_id": str, "timed_out": bool}.
    - Локальные refs прогоняются через upload_reference (лимит рефов зависит от модели —
      см. паспорт; при превышении — MagnificError).
    - Поллинг до COMPLETED или пока не истёк timeout.
    - timeout истёк, а задача ещё жива → НЕ ошибка: вернуть {"images": [], "task_id": ...,
      "timed_out": True}, чтобы вызывающий отдал task_id Hermes'у (fallback «номерок»).
    - FAILED / невалидный ключ / нет кредитов / сеть → MagnificError с понятным текстом."""
```

Сохранение файла — по образцу `nano.save_image`: имя `magnific_<model>_<UTC-stamp>.png`
в `out_dir`. Скачивание готовой картинки — GET по URL из ответа, запись байтов.

**Aspect:** у разных моделей Magnific свой набор допустимых значений — НЕ хардкодь единый
`VALID_ASPECTS`, как у Nano. Передавай `aspect` как есть (пустой → не передавать параметр);
доверяй валидации API и пробрасывай его ошибку через `MagnificError`.

### 5.2. `gf/config.py` — новые настройки

Добавь в `Settings` и `load_settings()` (паттерн env, как у остальных):
- `freepik_api_key: "str | None"` ← `GF_FREEPIK_API_KEY` (ключ живёт на заводе, не у Hermes).
- `magnific_base_url: str` ← `GF_MAGNIFIC_BASE_URL` (дефолт — подтверждённый в разделе 3).
- `magnific_timeout: int` ← `GF_MAGNIFIC_TIMEOUT` (дефолт 180).
- `magnific_poll_interval: int` ← `GF_MAGNIFIC_POLL_INTERVAL` (дефолт 3).

Обнови `.env.example` и секцию Config в `README.md`.

### 5.3. `gf/pricing.py` — цены per-model

Добавь таблицу и функцию (рядом с существующей `estimate`):
```python
_MAGNIFIC_PER_IMAGE_USD = {           # грубые оценки; уточнить/пометить как approximate
    "mystic": 0.10,
    "seedream-v4-5-edit": 0.06,
    "flux-kontext-pro": 0.05,
}
_MAGNIFIC_DEFAULT_USD = 0.10          # неизвестная модель → консервативно дороже

def estimate_magnific(model: str, n: int = 1) -> float: ...
```
Точные тарифы Magnific не публикует — числа приблизительные, в комментарии честно пометь это
и укажи, что источник истины — счёт Freepik.

### 5.4. `gf/mcp_server.py` — новый инструмент + impl

Добавь `_generate_magnific_impl(...)` — **клон `_generate_final_impl`** со следующими отличиями:
1. `target = f"magnific/{model}"` вместо зашитого `writer_final_target`; авто-путь через тот же
   `_maybe_rewrite` (fail-open).
2. `cost = pricing.estimate_magnific(model, 1)`; бюджет-гейт через существующий `budget.check`.
3. Бэкенд — `magnific.generate(...)`; из результата достаёшь `images`, `task_id`, `timed_out`.
4. `budget.log_cost(project_dir, f"magnific/{model}", 1, cost, note=...)` **только если реально
   сгенерировали** (не логируй трату, если `timed_out` и картинки нет — иначе тетрадка врёт;
   но если API уже списал кредиты на старте задачи — обсуди с Киром, что честнее; по умолчанию
   логируем по факту наличия картинки).
5. Ответ Hermes'у: `{images, backend: "magnific", model, cost_usd, spent_usd, prompt_used,
   prompt_log, writer_skipped, task_id, timed_out}`.

Зарегистрируй MCP-инструмент:
```python
@mcp.tool()
def gf_generate_magnific(project: str, model: str, prompt: str,
                         refs: "list | None" = None, aspect: str = "",
                         raw: bool = False) -> dict:
    """Сгенерировать картинку через Magnific (Freepik). model — обязателен
    (mystic | seedream-v4-5-edit | flux-kontext-pro); target паспорта = magnific/<model>.
    prompt = задача (райтер перепишет); raw=True — дословно. refs — локальные пути (до лимита
    модели), завод сам зальёт их во внешнее хранилище."""
    return _generate_magnific_impl(project, model, prompt, refs, aspect, raw, settings=settings)
```

Валидация `model`: если паспорта `magnific/<model>` нет — райтер сам вернёт `WriterError`
со списком целей (на авто-пути превратится в `writer_skipped`; для явной валидации можно
проверить `writer.load_passport` заранее и вернуть чистый `{"error": ...}`). Предпочтителен
ранний чистый отказ на неизвестной модели.

### 5.5. `gf/cli.py` — CLI-зеркало

Добавь `gf generate-magnific <project> <model> "<задача>" [--refs ...] [--aspect ...] [--raw]`
по образцу существующих CLI-команд (`gf write-prompt`, `gf generate-*`). Нужен для живого смоука.

### 5.6. `gf/writer.py` — НЕ ТРОГАТЬ

Промпт-слой уже умеет любой `target` с паспортом. Ничего менять не нужно.

---

## 6. Поток данных

**Явный вызов `gf_generate_magnific(project, model="seedream-v4-5-edit", prompt="...", refs=[...])`:**
1. (`raw=False`) `_maybe_rewrite` → `writer.write_prompt(target="magnific/seedream-v4-5-edit")`
   → грамотный промпт (fail-open: райтер упал → сырой текст + `writer_skipped`).
2. `pricing.estimate_magnific(model)` → `budget.check` (гейт по `GF_IMAGE_CAP_USD`).
   Не прошёл гейт → `{"error": ...}` до траты денег.
3. `magnific.generate(...)`:
   a. каждый локальный реф → `upload_reference` → http-URL;
   b. POST задачу (model, prompt, refs-URL, aspect) → `task_id`;
   c. поллинг статуса до COMPLETED (или timeout);
   d. скачать картинку → `media/generated/<date>/magnific_<model>_<stamp>.png`.
4. `budget.log_cost("magnific/<model>")` (по факту картинки) + провенанс промпта уже записан райтером.
5. Ответ: пути + `prompt_used` + `prompt_log` + `cost_usd`/`spent_usd` + `task_id`/`timed_out`.

**`raw=True`** — райтер не вызывается, `prompt` уходит как есть.

**Итерация «не то»:** отдельного механизма нет — Hermes зовёт снова, при желании передав правку
в промпт (как и для остальных бэкендов).

---

## 7. Обработка ошибок

Принцип завода: **явный путь — fail-closed (чистая ошибка), авто-путь райтера — fail-open (флаг).**
Сам Magnific-бэкенд ошибку генерации отдаёт наружу — генерация картинки либо удалась, либо нет.

| Ситуация | Поведение |
|---|---|
| Нет `GF_FREEPIK_API_KEY` | `{"error": "...укажи GF_FREEPIK_API_KEY..."}` (fail-closed), до вызова API |
| Неизвестная `model` (нет паспорта) | Ранний `{"error": ...}` со списком доступных `magnific/*` |
| Райтер упал (нет ключа Anthropic/API-ошибка) | fail-open: генерация по сырому тексту + `writer_skipped: "<причина>"` |
| Не прошёл бюджет-гейт | `{"error": gate.reason, ...}` до траты |
| Реф не найден / неподдерживаемый тип / превышен лимит рефов модели | `MagnificError` → `{"error": ...}` |
| Upload референса упал | `MagnificError` → `{"error": ...}` |
| Задача FAILED / нет кредитов / невалидный ключ / rate-limit | `MagnificError` с понятным текстом → `{"error": ...}` |
| Таймаут поллинга, задача ещё жива | НЕ ошибка: `{"images": [], "task_id": ..., "timed_out": true}` — Hermes может дозабрать |
| Сеть недоступна (ConnectionError/Timeout) | `MagnificError` с подсказкой → `{"error": ...}` |

---

## 8. Тестирование

Паттерн завода: **pytest, без живых API, инжектируемые зависимости.**

`tests/test_magnific.py` (новый) — с `FakeSession` (по образцу того, как в тестах мокается
`session`/`client`):
- `upload_reference`: успешная загрузка → URL; ошибка загрузки → `MagnificError`.
- `generate`: happy path (POST → poll: IN_PROGRESS ×N → COMPLETED → download → сохранённый файл);
  маппинг ответа; имя файла `magnific_<model>_*.png`.
- поллинг: несколько IN_PROGRESS перед COMPLETED; статус FAILED → `MagnificError`.
- таймаут: задача не успевает → `timed_out=True`, `images=[]`, `task_id` присутствует.
- лимит рефов / несуществующий реф / неподдерживаемый тип → `MagnificError`.
- ошибки: 401 (ключ), «нет кредитов», сеть → `MagnificError`.

`tests/test_mcp_generate.py` (расширить):
- `raw=True` — райтер не вызван, `prompt` дословно.
- `raw=False` — `prompt_used` из фейк-райтера; `writer_skipped` при выключенном/упавшем райтере.
- неизвестная `model` → чистый `{"error": ...}`.
- бюджет-гейт отбивает до вызова бэкенда.
- `timed_out=True` пробрасывается в ответ; трата не логируется без картинки.

`pricing`: `estimate_magnific` для известной/неизвестной модели.

Живой смоук — вручную через CLI (нужен реальный ключ):
`gf generate-magnific <project> seedream-v4-5-edit "тестовая задача" --aspect 9:16`.

---

## 9. Вне scope v1 (не делать)

- Видео (Kling) и upscale — отдельная фаза.
- `simulate_cost` и точный кредитный биллинг — сейчас плоская таблица.
- Vision-режим райтера (передавать сами картинки-референсы в райтер) — как и в промпт-слое, потом.
- Автоматический выбор модели заводом — модель выбирает Hermes/Кир явным параметром.
- Итеративный «поправь предыдущий» механизм — Hermes зовёт заново.

---

## 10. Definition of Done

- [ ] REST-детали Freepik подтверждены и записаны в шапке `backends/magnific.py` (раздел 3).
- [ ] `gf/backends/magnific.py`: upload + generate + poll + download, свои исключения, инжектируемый `session`.
- [ ] `gf_generate_magnific` в `mcp_server.py` + CLI-зеркало в `cli.py`.
- [ ] `config.py` (+ `.env.example`, `README.md`), `pricing.py` обновлены.
- [ ] `writer.py` НЕ изменён.
- [ ] Тесты зелёные: `python -m pytest` (без живых API).
- [ ] Живой смоук через CLI прошёл хотя бы на одной модели (или явно отмечено, что нужен ключ от Кира).
- [ ] Ответ инструмента содержит `prompt_used`, `prompt_log`, `writer_skipped`, `cost_usd`,
      `spent_usd`, `task_id`, `timed_out`.
- [ ] Ошибки ведут себя по таблице раздела 7 (fail-closed явный / fail-open авто).

---

## 11. Подсказки по процессу (для Claude Code)

- Есть плагин **superpowers**: уместно прогнать реализацию через `test-driven-development`
  и, при желании, `writing-plans` (разбить этот док на пошаговый план) перед кодом. Брейншторм
  уже сделан — повторно его не запускай.
- Не рефактори несвязанное. Держись границ этого дока.
- Если API из раздела 3 окажется устроен иначе, чем предполагает раздел 5 — **следуй факту API**,
  а этот док обнови (он спека, а не догма). Отметь расхождения Киру.
