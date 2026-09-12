# Content Factory — быстрый старт (fal.ai / Replicate через Codex)

Это генеративный завод: единая обёртка над платными AI-моделями. Ты описываешь задачу,
он запускает модель, ждёт результат и скачивает его к тебе в папку проекта.

Этот квикстарт — **только для fal.ai и Replicate через OpenAI Codex**. Им **не нужна никакая
локальная инфраструктура** (GPU, серверы) — достаточно Python и API-ключа. Остальные бэкенды
завода (ComfyUI, Nano, Dreamina) требуют локального железа/сервисов и здесь **не используются** —
просто не вызывай их.

---

## Что понадобится

1. **Python ≥ 3.10** (`python --version`).
2. **OpenAI Codex CLI** (уже установлен и работает у тебя).
3. **Аккаунт fal.ai** и/или **Replicate** с положенными кредитами (вызовы платные, помодельно):
   - fal: https://fal.ai → Dashboard → **Keys** → создать ключ.
   - Replicate: https://replicate.com → Account → **API tokens** → создать токен (`r8_...`).
   - ⚠️ Ключ — **твой личный**. Не бери чужой: это чужие деньги, лимиты и риск утечки.

---

## Шаг 1. Установить

```bash
git clone <URL-репозитория> content-factory
cd content-factory
python -m pip install -e ".[dev]"
```

После установки в PATH появляется команда `gf`. Проверь: `gf --help`.

---

## Шаг 2. Прописать ключи

Создай файл `.env` в корне проекта (он в `.gitignore` — в git не попадёт):

```
FAL_KEY=твой_ключ_fal
REPLICATE_API_TOKEN=r8_твой_токен_replicate
```

Достаточно того сервиса, которым будешь пользоваться (можно только `FAL_KEY`).

---

## Шаг 3. Проверить, что всё живо

```bash
gf serve            # должен запуститься MCP-сервер (Ctrl+C чтобы остановить)
gf fal-list-workflows   # если FAL_KEY верный — вернёт список (или пусто), не ошибку авторизации
```

Если `gf serve` поднимается и `fal-list-workflows` не ругается на ключ — готово.

---

## Шаг 4. Подключить к Codex

Codex читает `~/.codex/config.toml` (формат **TOML**, не JSON). Добавь блок:

```toml
[mcp_servers.generation_factory]
command = "gf"
args = ["serve"]
```

Если `gf` не находится по имени — укажи Python явно:

```toml
[mcp_servers.generation_factory]
command = "python"
args = ["-m", "gf.cli", "serve"]
```

Проверь подключение:

```bash
codex mcp list
```

Должен появиться `generation_factory` с инструментами `gf_fal_run`, `gf_replicate_run`,
`gf_fal_list_workflows` и др.

> ⚠️ **Ключи из `.env`.** Завод читает `.env` относительно рабочей директории процесса.
> Если Codex запускает `gf serve` не из папки проекта — ключ может не найтись. Тогда либо
> пропиши ключи в **системные переменные окружения**, либо добавь в блок конфига рабочую
> директорию/`env` (см. доку Codex по `mcp_servers`).

---

## Как пользоваться

Оба инструмента — **generic-обёртки**: ты сам выбираешь модель и собираешь `input` (как при
прямом вызове API площадки), а завод берёт на себя запуск, ожидание и скачивание результата.

**Через Codex** — просто попроси агента, например: «сгенерируй картинку через fal-ai/nano-banana-pro
с промптом …, проект — <абсолютный путь>». Codex вызовет `gf_fal_run`.

**Через CLI** (для проверки вручную):

```bash
# fal: эндпоинт + input (JSON). project — АБСОЛЮТНЫЙ путь к папке проекта.
gf fal-run C:\Projects\demo fal-ai/nano-banana-pro "{\"prompt\":\"cinematic portrait\"}"

# Replicate: model = "owner/name" ИЛИ 64-hex version, + input (JSON).
gf replicate-run C:\Projects\demo black-forest-labs/flux-schnell "{\"prompt\":\"a red fox\"}"
```

Результаты скачиваются в `<project>\media\generated\<дата>\` (видео — в подпапку `video\`).

### Примеры моделей fal (проверены для этой интеграции)
- `fal-ai/nano-banana-pro` — картинки (t2i / с референсами);
- `bytedance/seedance-2.0/text-to-video`, `.../image-to-video`, `.../reference-to-video` (+fast-варианты);
- `fal-ai/kling-video/v3/standard/image-to-video`;
- `fal-ai/wan-25-preview/image-to-video`.

Каталог моделей: fal — https://fal.ai/models · Replicate — https://replicate.com/explore

---

## Важные правила

- **`project` — всегда абсолютный путь** (например `C:\Projects\demo` или `/home/user/demo`).
  Относительный путь завод отклонит (чтобы файлы не ушли мимо проекта).
- **Платно помодельно.** Для первых проб бери недорогие/быстрые модели (например `flux-schnell`
  на Replicate). Стоимость логируется в `<project>\media\.gf_cost_log.jsonl`.
- **Ключи не коммить.** `.env` уже в `.gitignore` — так и оставь.

---

## Ограничения этого пути

- **Работают только fal и Replicate.** Остальные бэкенды (ComfyUI/Nano/Dreamina) требуют локального
  железа/сервисов — не трогай их, они не нужны для fal/replicate.
- **Локальные файлы в input.** Передать локальный файл (референс) можно маркером `@путь` — но регэксп
  заточен под **Windows-пути** (`@C:/path/file.png`). На **macOS/Linux** POSIX-пути (`@/home/...`)
  пока не распознаются — генерация **по промпту без локальных входов** работает везде, а загрузка
  локальных референсов на не-Windows потребует доработки.

---

## Если что-то не так

| Симптом | Причина / решение |
|---|---|
| `Missing FAL_KEY` / `REPLICATE_API_TOKEN` | Ключа нет в `.env`, или процесс запущен не из папки проекта → пропиши ключ в системную env |
| `401` при вызове | Ключ невалиден — пересоздай на сайте площадки |
| `project должен быть абсолютным путём` | Передай полный путь, не относительный |
| `codex mcp list` не показывает сервер | Проверь `~/.codex/config.toml` (TOML-синтаксис) и что `gf`/`python -m gf.cli serve` запускается вручную |
| Дорого / долго | Возьми более дешёвую/быструю модель; видео дороже картинок |

---

Всё. Для fal/Replicate этого достаточно: `clone → pip install → свой ключ в .env → блок в
~/.codex/config.toml`.
