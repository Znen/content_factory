# Задача: видео-бэкенд завода на Dreamina CLI (Фаза VG — Seedance)

**Дата:** 2026-07-09
**Статус:** дизайн одобрен (брейншторм с Киром), готов к реализации
**Исполнитель:** Claude Code в терминале
**Тип:** новая фича — первый видео-бэкенд завода (генерация видео, не только промпты)

---

## 0. Для исполнителя — прочитай первым

Ты добавляешь в завод `content-factory` возможность **реально генерировать видео** через
**Dreamina CLI (JiMeng / 即梦, ByteDance)** — модель Seedance. До сих пор завод умел только
картинки (ComfyUI, Nano) и умел лишь *писать* видео-промпты (паспорт `video/seedance-2-0`).
Теперь он сам запускает генерацию, ведёт реестр задач и забирает готовые клипы.

**Обязательный порядок:**

1. **Прочитай первоисточники по Dreamina CLI** (там всё — команды, флаги, модели, реальные грабли):
   - `Q:\Lion Films. AI studio\tools\dreamina-cli\DREAMINA_CLI.md` — полное руководство CLI 1.4.1,
     проверенное вживую. Команды, модели Seedance, async-модель (submit → `submit_id` →
     `query_result`, флаг `--poll`), подводные камни.
   - `Q:\Lion Films. AI studio\tools\videogen\backends\dreamina.py` — **рабочий образец
     оркестрации** из старого завода: инъецируемый `_runner`, staging путей без пробелов,
     retry+backoff, VIP-очередь, встроенный selftest. **Твой `backends/dreamina.py` строится по
     нему** (перенеси паттерны, адаптируй под новый CLI-бинарь `dreamina` и реестр задач).
2. **Прочитай образцы бэкендов завода** — `gf/backends/nano.py`, `gf/backends/comfyui.py`
   (инъекция зависимостей для тестов, свои исключения). И `gf/mcp_server.py` — как устроены
   `_generate_final_impl` / `_maybe_rewrite` (авто-путь через райтера), которые ты клонируешь.
3. **Прочитай `gf/promptdocs/video/seedance-2-0.md`** — паспорт уже написан; райтер по нему
   пишет промпт движения. Твой бэкенд вызывает райтера с `target="video/seedance-2-0"`.
4. Изучи `gf/budget.py`, `gf/media.py`, `gf/pricing.py`, `gf/config.py` — точки интеграции.

**Процесс:** TDD (инъецируемый `_runner`, без живого CLI — как selftest старого `dreamina.py`),
fail-closed на явном пути, fail-open на авто-пути райтера. Комментарии по-русски, идентификаторы
и промпты по-английски.

**⚠️ Ключевая особенность:** живой запуск требует установленного и залогиненного Dreamina CLI
(`dreamina login --headless`) и кредитов JiMeng. Живой смоук возможен только когда Кир это
обеспечит — весь код и тесты пишутся на моках.

---

## 1. Контекст: что за завод

`content-factory` (пакет `gf`) — генеративный MCP-слой для Hermes. Существующие бэкенды:
ComfyUI (черновики), Nano (финалы, заблокирован), Magnific (картинки, в разработке — Фаза M).
Промпт-слой (`gf/writer.py` + `promptdocs/`) пишет промпты по «паспортам»; видео-паспорта уже
есть (`video/{veo-3-1,seedance-2-0,wan-2-5,runway-gen-4}`). Бюджет — `<project>/media/.gf_cost_log.jsonl`.
Хранилище — `<project>/media/generated/<date>/`.

**Эта фаза = первый видео-бэкенд.** Только Seedance через Dreamina CLI (Veo/Wan/Runway живут на
других платформах — отдельные бэкенды позже, вне scope).

---

## 2. Что строим (одним абзацем)

Модуль `gf/backends/dreamina.py` (subprocess-обёртка над бинарём `dreamina`) + три MCP-инструмента:
`gf_generate_video` (запустить генерацию), `gf_list_video_jobs` (реестр задач + их статусы),
`gf_fetch_video` (дозабрать готовый клип по `submit_id`). Поток: Hermes → (райтер пишет промпт
движения по паспорту Seedance) → staging входных картинок (пути без пробелов + сжатие) → запуск
Dreamina-команды → **гибридное ожидание** (подождать ~2-3 мин; готово → скачать mp4; не готово →
записать `submit_id` в реестр и вернуть «номерок») → учёт кредитов. Позже `gf_fetch_video` /
`gf_list_video_jobs` дозабирают готовое из реестра.

---

## 3. Дизайн-решения (не пересматривать без Кира)

| Развилка | Решение |
|---|---|
| Платформа | **Только Seedance через Dreamina CLI.** Veo/Wan/Runway — не Dreamina, отдельные бэкенды позже. |
| Транспорт | Subprocess над бинарём `dreamina` (по образцу старого `videogen/backends/dreamina.py`). |
| Режимы v1 | **4 команды:** `image2video` (i2v, оживить winner), `text2video` (t2v), `frames2video` (старт+финал), `multimodal2video` (флагман: картинки+видео+аудио, 1080p VIP). `multiframe2video` — **вне v1**. |
| Ожидание | **Гибрид:** попытаться `--poll` ~180с; готово → скачать и отдать; не готово → записать `submit_id` в реестр, вернуть «номерок» + флаг `pending`. |
| Реестр задач | `<project>/media/.gf_video_jobs.jsonl` — завод сам помнит `submit_id`, Hermes/Кир не обязаны. |
| Забор результата | `gf_list_video_jobs` (список + живой статус) и `gf_fetch_video(submit_id)` (скачать mp4). |
| Промпт | как везде: `raw=False` → райтер по `video/seedance-2-0`; `raw=True` → дословно. |
| Стоимость | Плоская таблица кредитов per-модель/разрешение (из доки). Учёт в кредитах; USD-оценка по курсу кредита (уточнить у Кира — см. §5.4). |
| Модель | Параметр (`seedance2.0` / `2.0fast` / `2.0_vip` / `2.0fast_vip`; дефолт `seedance2.0fast` — дёшево для проб). |
| Обязательные защиты | staging путей без пробелов + resolution-matching (сжатие input) — из практики старого завода (иначе upload молча фейлит с частичным списанием кредитов). |

---

## 4. Dreamina CLI — как вызывать (сверяйся с DREAMINA_CLI.md)

Бинарь `dreamina`. Все генерации **асинхронные**: submit → `submit_id` → `query_result`.
Флаг `--poll=N` ждёт результат в терминале до N секунд. Скачивание: `query_result
--submit_id=<id> --download_dir=<dir>`. Список задач: `list_task` (фильтры `--gen_status`,
`--gen_task_type`, `--submit_id`). Баланс: `user_credit`.

Маппинг режимов (уточни точные флаги по help-дампу / DREAMINA_CLI.md):

| `mode` | Команда | Ключевые флаги |
|---|---|---|
| `i2v` | `image2video` | `--image` `--prompt` `--model_version` `--duration` (⚠️ `--ratio` НЕ принимает — из картинки) |
| `t2v` | `text2video` | `--prompt` `--model_version` `--duration` `--ratio` `--video_resolution` |
| `frames` | `frames2video` | `--first` `--last` `--prompt` `--model_version` `--duration` |
| `multimodal` | `multimodal2video` | `--image` (до 9) `--video` (до 3) `--audio` (до 3) `--prompt` `--model_version` `--duration` `--ratio` `--video_resolution` |

**Модели:** `seedance2.0`, `seedance2.0fast`, `seedance2.0_vip`, `seedance2.0fast_vip`
(подчёркивание перед `vip` обязательно — без него API молча ставит в стандартную очередь).
**Длительность:** 4–15с. **1080p для Seedance** — только через `multimodal2video
--model_version=seedance2.0_vip --video_resolution=1080p` (в остальных командах 720p).

---

## 5. Компоненты

### 5.1. `gf/backends/dreamina.py` (новый) — subprocess-обёртка

По образцу старого `videogen/backends/dreamina.py`: инъецируемый `_runner(cmd, cwd) ->
CompletedProcess`, свои исключения, никакой связи с бюджетом/проектом (это в `mcp_server.py`).

Примерная поверхность (уточни по факту CLI):

```python
class DreaminaError(Exception): ...
class DreaminaPending(Exception):   # или возвращай флаг — задача принята, но не готова за poll
    def __init__(self, submit_id): ...

def stage_and_shrink(path: Path, resolution: str) -> Path:
    """Копия input в no-space temp + ресайз/сжатие под resolution-matching rule:
    720p → 1280×720 q85 <500KB; 1080p → 1920×1080 q92 <1MB. Требует Pillow."""

def submit(mode: str, *, prompt: str, model: str, inputs: dict, duration: int,
           ratio: str = "", resolution: str = "720p", poll: int = 180,
           _runner=...) -> dict:
    """Запустить генерацию. inputs зависит от mode (image / first+last / images+video+audio).
    Стейджит+сжимает входные картинки, шеллит dreamina <cmd> ... --poll=<poll>.
    Возвращает {"status": "success"|"pending", "submit_id": str,
                "output": Path|None}  — success если успел за poll, иначе pending + submit_id."""

def fetch(submit_id: str, out_dir: Path, _runner=...) -> dict:
    """query_result --submit_id --download_dir. Возвращает {"status": "success"|"querying"|"fail",
    "output": Path|None, "fail_reason": str|None}. Скачанный mp4 → out_dir."""

def list_jobs(_runner=...) -> list[dict]:
    """dreamina list_task → список задач со статусами (для сверки с реестром)."""
```

Перенеси из старого образца: **staging путей без пробелов** (критично), **retry+backoff** на
flaky upload, выбор VIP-очереди. Имя выходного файла: `seedance_<mode>_<UTC-stamp>.mp4`.

### 5.2. Реестр задач — `<project>/media/.gf_video_jobs.jsonl`

Новый модуль или функции в `dreamina.py`/`budget.py`-стиле. Одна строка на задачу:
```json
{"ts": 1720500000.0, "submit_id": "3f6eb41f425d23a3", "mode": "i2v",
 "model": "seedance2.0fast", "task": "оживить winner-портрет",
 "prompt_used": "She slowly turns...", "resolution": "720p", "duration": 5,
 "status": "pending", "output": null, "date": "2026-07-09"}
```
Пишется при `submit` (status `pending`/`success`); обновляется при `fetch` (status `success` +
`output`, или `fail`). `gf_list_video_jobs` читает его и сверяет с живым `list_task`.

### 5.3. `gf/config.py` — новые настройки

- `dreamina_bin: str` ← `GF_DREAMINA_BIN` (дефолт `dreamina`; путь к бинарю, если не в PATH).
- `dreamina_poll_wait: int` ← `GF_DREAMINA_POLL_WAIT` (дефолт 180 — сколько ждать до «номерка»).
- `dreamina_default_model: str` ← `GF_DREAMINA_MODEL` (дефолт `seedance2.0fast`).
Обнови `.env.example` и README.

### 5.4. `gf/pricing.py` — кредиты Seedance

Плоская таблица кредитов (из DREAMINA_CLI.md, 5-сек ориентир):
```python
_DREAMINA_CREDITS = {           # (model, resolution) → credits per ~5s
    ("seedance2.0fast_vip", "720p"): 55,
    ("seedance2.0_vip", "720p"): 70,
    ("seedance2.0_vip", "1080p"): 165,
    # ... остальные — из user_credit / доки; неизвестное → консервативный максимум
}
def estimate_dreamina_credits(model, resolution, duration) -> int: ...
```
**❓ Курс кредита → USD не зафиксирован** — уточни у Кира (сколько $ за кредит) ИЛИ логируй в
`budget` величину кредитов в `note`, а `cost_usd` оставляй грубой оценкой/0 с пометкой. Не
выдумывай курс. Кредиты дороги — обязательно предупреждай в ответе перед 1080p (×3 от 720p).

### 5.5. `gf/mcp_server.py` — три инструмента

```python
@mcp.tool()
def gf_generate_video(project: str, mode: str, prompt: str,
                      image: str = "", first: str = "", last: str = "",
                      images: "list | None" = None, video: "list | None" = None,
                      audio: "list | None" = None, model: str = "",
                      duration: int = 5, ratio: str = "", resolution: str = "720p",
                      raw: bool = False) -> dict:
    """Сгенерировать видео через Dreamina (Seedance). mode: i2v|t2v|frames|multimodal.
    prompt = задача движения (райтер перепишет по video/seedance-2-0); raw=True — дословно.
    Гибрид: ждёт до GF_DREAMINA_POLL_WAIT сек; не успел → возвращает submit_id (pending),
    задача пишется в реестр. Возвращает {status, submit_id, output?, prompt_used, prompt_log,
    writer_skipped, credits, warning?}."""
```
- Авто-путь через `_maybe_rewrite` (fail-open) с `target="video/seedance-2-0"`.
- i2v-`image` — обычно winner из курации (путь внутри проекта).
- Учёт: пиши кредиты в реестр и в `budget` (по факту — при `success`; для `pending` — при `fetch`).

```python
@mcp.tool()
def gf_list_video_jobs(project: str) -> dict:
    """Реестр видео-задач проекта + их живой статус (из dreamina list_task).
    {jobs: [{submit_id, mode, model, task, status, output?}, ...]}."""

@mcp.tool()
def gf_fetch_video(project: str, submit_id: str) -> dict:
    """Дозабрать готовый клип по номерку: query_result → скачать mp4 в media/generated/<date>/,
    обновить реестр, учесть кредиты. Возвращает {status, output?, fail_reason?}.
    querying → ещё не готово; fail → причина; success → путь к mp4."""
```

CLI-зеркала: `gf generate-video`, `gf list-video-jobs`, `gf fetch-video`.

### 5.6. `gf/writer.py` — НЕ ТРОГАТЬ

Райтер уже умеет `video/seedance-2-0`. Бэкенд просто передаёт этот target.

---

## 6. Поток данных

**Запуск (`gf_generate_video`, гибрид):**
1. `raw=False` → райтер по `video/seedance-2-0` → промпт движения (fail-open → `writer_skipped`).
2. Стейджинг входных картинок: копия в no-space temp + сжатие под `resolution` (resolution-matching).
3. `dreamina <cmd> ... --poll=<GF_DREAMINA_POLL_WAIT>`.
4. Успел за poll → скачать mp4 в `media/generated/<date>/`, записать в реестр `success`, учесть кредиты,
   вернуть `{status: "success", output, ...}`.
5. Не успел → записать `submit_id` в реестр `pending`, вернуть `{status: "pending", submit_id, ...}`.

**Дозабор (`gf_fetch_video`):** `query_result --submit_id --download_dir` → success: скачать mp4,
обновить реестр, учесть кредиты; querying: вернуть статус; fail: `fail_reason`.

**Список (`gf_list_video_jobs`):** прочитать реестр + сверить с `dreamina list_task` → отдать статусы.

---

## 7. Обработка ошибок (из практики DREAMINA_CLI.md)

| Ситуация | Поведение |
|---|---|
| CLI не установлен / не залогинен | `{"error": "...установи/залогинь dreamina (dreamina login --headless)..."}` (fail-closed) |
| Райтер упал | fail-open: генерация по сырому `prompt` + `writer_skipped` |
| Путь с пробелами | НЕ ошибка — обязательный staging убирает пробелы до вызова CLI |
| Input >1–2 МБ | НЕ ошибка — resolution-matching сжимает до <500KB/<1MB до вызова |
| `pre-TNS check did not pass` (контент-фильтр; кредиты списаны) | `{"error": "...контент отклонён фильтром Dreamina; убери акцент на теле, добавь одежду, целься в лицо..."}` + не ретраить вслепую |
| `AigcComplianceConfirmationRequired` | `{"error": "...подтверди модель на сайте Dreamina Web и повтори..."}` |
| Задача-призрак (`no history found`) | вернуть статус с пометкой; не падать; предложить проверить `~/.dreamina_cli/logs` |
| Таймаут poll (задача жива) | НЕ ошибка — `{status: "pending", submit_id}` + запись в реестр |
| flaky upload / rc≠0 | retry+backoff (как в старом образце) → затем `DreaminaError` |
| Недостаточно кредитов | `DreaminaError` с понятным текстом |

---

## 8. Тестирование

Паттерн: pytest, инъецируемый `_runner` (эмулирует `dreamina`-вызовы), **без живого CLI** — ровно
как selftest старого `videogen/backends/dreamina.py`.

`tests/test_dreamina.py` (новый):
- staging: путь с пробелами → cwd/арг без пробелов; input >лимита → сжат (мок Pillow или реальный).
- `submit` happy path: успел за poll → `status=success`, mp4 на месте.
- `submit` таймаут: не успел → `status=pending`, `submit_id` возвращён, retry на flaky upload.
- `fetch`: querying → querying; success → скачан mp4; fail → `fail_reason`.
- маппинг режимов: i2v/t2v/frames/multimodal собирают правильную команду и флаги; i2v не шлёт `--ratio`.
- реестр: submit пишет строку `pending`; fetch обновляет на `success` + `output`.
- ошибки: не залогинен, pre-TNS, задача-призрак → корректные исключения/сообщения.

`tests/test_mcp_generate.py` (расширить): `raw=True` не трогает райтера; `raw=False` — `prompt_used`
из фейк-райтера; `writer_skipped` при упавшем райтере; `pending` пробрасывается; кредиты не
логируются, пока нет `success`.

`pricing`: `estimate_dreamina_credits` для известной/неизвестной пары.

Живой смоук (нужен залогиненный CLI + кредиты, вручную):
`gf generate-video <project> i2v "оживить портрет: лёгкий поворot головы" --image <winner.png>
--model seedance2.0fast --duration 5`.

---

## 9. Вне scope v1 (не делать)

- Veo / Wan / Runway (не Dreamina — отдельные бэкенды/платформы).
- `multiframe2video` (2–20 кадров), `image_upscale`, `text2image`/`image2image` Dreamina.
- Фоновый авто-забор готовых задач (демон/крон) — забор инициирует Hermes/Кир через инструменты.
- Точный биллинг в USD, если курс кредита не дан Киром — логируем кредиты, USD-оценка грубая.

---

## 10. Definition of Done

- [ ] `gf/backends/dreamina.py`: `submit` (гибрид poll), `fetch`, `list_jobs`, staging+сжатие,
      инъецируемый `_runner`, свои исключения, retry на flaky upload.
- [ ] Реестр `<project>/media/.gf_video_jobs.jsonl`: запись при submit, обновление при fetch.
- [ ] `gf_generate_video` / `gf_list_video_jobs` / `gf_fetch_video` в `mcp_server.py` + CLI-зеркала.
- [ ] `config.py` (+ `.env.example`, README), `pricing.py` (кредиты) обновлены.
- [ ] `writer.py` НЕ изменён; авто-путь через `video/seedance-2-0`.
- [ ] Все 4 режима (i2v/t2v/frames/multimodal) собирают корректную команду; i2v без `--ratio`.
- [ ] Ошибки по таблице §7 (fail-closed явный / fail-open авто; pre-TNS/призрак/таймаут корректны).
- [ ] `python -m pytest` зелёный (на моках, без живого CLI).
- [ ] Ответ инструмента: `status`, `submit_id`, `output`, `prompt_used`, `prompt_log`,
      `writer_skipped`, `credits`, предупреждение о цене для 1080p.

---

## 11. Подсказки по процессу

- Есть плагин **superpowers**: прогони через `test-driven-development`; можно `writing-plans`
  (разбить на пошаговый план). Брейншторм уже сделан — не повторяй.
- **Старый `videogen/backends/dreamina.py` — твой лучший друг:** там уже решены staging путей с
  пробелами и retry. Не изобретай — адаптируй под новый бинарь `dreamina`, реестр и 4 режима.
- Если реальные флаги CLI разойдутся с §4 — **следуй help-дампу `dreamina <cmd> --help` /
  DREAMINA_CLI.md**, а спеку обнови и отметь расхождения Киру.
- Не рефактори несвязанное. Держись границ этого дока.
