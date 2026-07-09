---
target: video/seedance-2-0
platform: seedance
syntax: natural
max_len: 800           # жёсткого лимита CLI не документирует; Seedance любит компактный связный промпт, не простыню
negative: false        # у Dreamina CLI нет negative-флага — нежелательное убираем позитивным перефразом (см. ниже)
refs: multi            # image2video: 1; frames2video: 2 (старт+финал); multiframe2video: 2-20; multimodal2video: до 9 картинок
updated: 2026-07-09
sources: ["Q:/Lion Films. AI studio/tools/dreamina-cli/DREAMINA_CLI.md (CLI 1.4.1, live-verified 2026-04)", "Q:/Lion Films. AI studio/tools/videogen/backends/dreamina.py", "docs/hermes-prompting-analysis-2026-07-06.md §4"]
---
# Как писать промпт для Seedance 2.0 (t2v + i2v + multi-shot)

Контекст: видео-модель ByteDance (Seedance 2.0), у Lion Films исполняется через **Dreamina CLI (JiMeng / 即梦)** — это **известный, проверенный вживую путь** (в отличие от Veo/Wan/Runway, чей путь ещё не выбран). Промпт натуральным языком; модель сильна в кино-движении и длинных клипах (4–15 секунд — больше, чем у Kling/Runway). Разрешение 720p (1080p — только через VIP-режим `multimodal2video`, см. «Особенности»). Асинхронно: submit → `submit_id` → `query_result` (флаг `--poll` ждёт в терминале). Режимы маппятся на команды CLI напрямую — пиши промпт под конкретный режим:

| Режим | Команда CLI | Вход |
|---|---|---|
| t2v | `text2video` | только промпт |
| i2v | `image2video` | 1 картинка + промпт (движение) |
| first+last | `frames2video` | старт + финал кадры + промпт перехода |
| multi-shot | `multiframe2video` | 2–20 картинок + промпты переходов |
| flagship / 1080p | `multimodal2video` | картинки+видео+аудио, VIP |

## Text-to-video (t2v)

`text2video` — модель рисует сцену и движение с нуля. Структура как у кино-t2v: **сцена/субъект → действие с направлением → движение камеры → темп → свет/стиль**. Seedance хорошо держит длинные планы (до 15 с) и плавную камеру. Одно главное движение камеры + одно действие субъекта на клип; для нескольких сцен — `multiframe2video`, не перегруз одного промпта.

`dreamina text2video --prompt="neon city at night, slow camera pan across the skyline, rain reflecting the lights, cinematic" --model_version=seedance2.0 --duration=10 --ratio=16:9 --video_resolution=720p --poll=180`

## Image-to-video (i2v)

`image2video` — композиция задана стартовым кадром, промпт описывает **только движение и камеру** (как в Kling). Не переописывай, что уже на картинке. **Важно: `image2video` не принимает `--ratio`** — соотношение сторон берётся из картинки автоматически; нужен другой ratio → ресайзь кадр заранее.

`dreamina image2video --image=./hero.jpg --prompt="camera slowly pushes in, wind moves the hair, coat sways gently" --model_version=seedance2.0 --duration=6 --poll=180`

## Multi-shot / раскадровка

Два пути связной истории из нескольких опорных кадров:

- **`frames2video`** — старт + финал, модель строит переход сама: `--first=./summer.jpg --last=./winter.jpg --prompt="season changes from summer to winter"`. Промпт описывает **суть перехода**.
- **`multiframe2video`** — 2–20 картинок в связный нарратив. Для N картинок нужно **N−1 промптов переходов** и **N−1 длительностей**; каждый сегмент 0.5–8 с, общая длина ≥ 2 с:
  ```
  dreamina multiframe2video \
    --images ./a.jpg,./b.jpg,./c.jpg \
    --transition-prompt="walks from the forest to the city gate" \
    --transition-prompt="enters the building through the tall doors" \
    --transition-duration="4" --transition-duration="3"
  ```
  Пиши каждый transition-prompt как **действие перехода между двумя кадрами**, а не как отдельную статичную сцену. (Замечание: `multiframe2video` в CLI 1.4.1 идёт **не** на движке seedance2.0 — это отдельный нарративный пайплайн; для чисто-Seedance multi-shot используй цепочку `image2video`/`frames2video`.)

## Negative prompt

**Нет.** Dreamina CLI не даёт negative-флага. Нежелательное убирай **позитивным перефразом в самом промпте**: не «no camera shake», а `static locked-off camera`; не «no extra people», а `the street is empty except for the subject`. Список запретов в промпт не пиши — как у Gemini, упоминание объекта повышает его вероятность.

## Параметры

| Параметр (CLI-флаг) | Значения | Комментарий |
|---|---|---|
| `--model_version` | `seedance2.0fast` (дефолт, дешевле) \| `seedance2.0` (макс. качество) \| `seedance2.0_vip` \| `seedance2.0fast_vip` (VIP-очередь) | VIP-имена **с подчёркиванием** перед `vip`; без него CLI примет, но API уронит в обычную очередь |
| `--duration` | 4–15 секунд | больше, чем у Kling/Runway; короткие (4–5 с) дешевле |
| `--ratio` | `1:1` `3:4` `4:3` `9:16` `16:9` `21:9` | **только для t2v/multimodal**; `image2video` ratio берёт из картинки |
| `--video_resolution` | `720p` (дефолт) \| `1080p` (только VIP через `multimodal2video`) | см. «Особенности» — 1080p ×3 по цене |
| `--poll` | секунды | ждать результат в терминале; без него — `submit_id` + `query_result` |
| `--session` | int (default 0) | привязка к диалогу Dreamina (1.4.1) |

## Особенности

**Проверено вживую (главная ценность этого паспорта):**
- **Пути с пробелами → тихий сбой аплоада + частичное списание кредитов.** Стейджь input в папку без пробелов (образец — `videogen/backends/dreamina.py`: staging + relative path + retry/backoff). Это правило #1.
- **Лимит файла 1–2 МБ + resolution-matching:** для 720p — ресайз input в **1280×720, q85, <500KB**; для 1080p — **1920×1080, q92, <1MB**. Крупнее → `upload image ... no file upload`. Сервер апскейлит сам, но матч input→output даёт чище результат.
- **pre-TNS контент-фильтр:** обнажённый/полуобнажённый торс (даже CGI), акцент на теле («muscular frame», камера по телу снизу вверх), нестандартный цвет кожи + мало одежды → `pre-TNS check did not pass`, **кредиты списываются**. Обход: фокус на лицо/действие/окружение, добавь одежду/доспехи в описание, камеру направляй в лицо (`camera pushes in to face close-up`). Фильтр проверяет и картинку, и промпт.
- **1080p:** только `multimodal2video --model_version=seedance2.0_vip --video_resolution=1080p` (в `-h` не показан, но работает — Pro Vision pipeline). Цена ×3 от привычной 720p fast — предупреждать перед запуском.
- **`AigcComplianceConfirmationRequired`** → подтвердить модель на сайте Dreamina Web, повторить.
- Очередь бывает огромной (сотни тысяч задач) — `--poll` с запасом или отложенный `query_result` по `submit_id`.

## Типовые фейлы

- **Пробел в пути к картинке** — самый частый и коварный: аплоад падает молча, кредиты частично списываются, а `submit_id` уже выдан. Всегда стейджить в no-space путь.
- **Тело/нагота в кадре или промпте** — TNS-фильтр отклонит и спишет кредиты; character sheet в полный рост часто не проходит — кропни до лица/плеч или добавь одежду.
- **`--ratio` на `image2video`** — `unknown flag`; ratio задаётся картинкой, ресайзь заранее.
- **Негатив-список в промпте** (`no blur, no watermark, low quality`) — у Seedance нет негатива; это шумит промпт и упоминает нежелательное. Убирай перефразом (`static camera`, `empty background`).
- **Имя VIP-модели без подчёркивания** (`seedance2.0vip`) — CLI молча уронит в обычную очередь без VIP-скорости; правильно `seedance2.0_vip`.
- **Тяжёлый input (>2МБ) без ресайза** — upload fail; всегда прогонять через resolution-matching (1280×720 q85 / 1920×1080 q92).
- **Ожидание 1080p от обычного `text2video`/`image2video`** — там только 720p; 1080p живёт лишь в VIP-`multimodal2video`.

## Примеры «задача → плохо → хорошо»

**1. (t2v)** Задача (RU): «Неоновый город ночью, медленная панорама по крышам, дождь»
- Плохо: `neon city, cyberpunk, 4k, ultra detailed, no blur, no low quality, amazing masterpiece` — SDXL-теги качества + негатив-список (у Seedance нет негатива), ни слова о движении/камере/темпе.
- Хорошо: `dreamina text2video --prompt="Slow camera pan across a rain-soaked neon cityscape at night, reflections shimmering on wet rooftops, steam rising from vents, moody cinematic atmosphere" --model_version=seedance2.0 --duration=10 --ratio=16:9 --video_resolution=720p --poll=180`

**2. (i2v)** Задача: оживить winner-кадр героя — шаг вперёд, плащ развевается, камера стоит
- Плохо: `dreamina image2video --image="./hero shot.png" --prompt="he moves, cinematic, dynamic, 1080p" --ratio=16:9` — **пробел в пути** (тихий сбой + списание), `--ratio` на i2v (unknown flag), 1080p недоступно тут, «he moves» без направления.
- Хорошо: `dreamina image2video --image=./hero.jpg --prompt="He takes a single step forward and looks into the camera, his coat swaying with the motion. Static locked-off camera." --model_version=seedance2.0 --duration=5 --poll=180` (input заранее ресайзнут в ≤720p, <500KB, путь без пробелов).

**3. (multi-shot)** Задача (RU): «Проход персонажа: лес → ворота города → внутрь здания» из трёх кадров
- Плохо: один `text2video` с промптом «character walks through forest then city then enters building, three scenes» — Seedance не разложит три локации в один связный клип, выйдет морфинг.
- Хорошо: `dreamina multiframe2video --images ./forest.jpg,./gate.jpg,./hall.jpg --transition-prompt="walks out of the forest toward the city gate" --transition-prompt="passes through the gate and enters the building" --transition-duration="4" --transition-duration="3"` (N=3 → 2 перехода, каждый — действие между кадрами).

**4. (t2v, риск TNS)** Задача: кино-превиз воина у костра, крупный план
- Плохо: `text2video --prompt="muscular bare-chested warrior, camera slowly tilts up his body from feet to face, firelight on skin"` — акцент на теле + tilt по телу → pre-TNS отклонит и спишет кредиты.
- Хорошо: `dreamina text2video --prompt="Close-up of a battle-worn warrior in fur and leather armor sitting by a campfire at night, firelight flickering on his weathered face, embers drifting, camera slowly pushes in to his eyes" --model_version=seedance2.0 --duration=6 --ratio=21:9 --poll=180` (фокус на лицо/атмосферу, одежда явно описана).

**5. (frames2video)** Задача: сезонный переход лето→зима для установочного плана
- Плохо: `image2video --image=./summer.jpg --prompt="it becomes winter"` — i2v из одного кадра не «дорисует» финальное состояние, переход выйдет случайным.
- Хорошо: `dreamina frames2video --first=./summer_valley.jpg --last=./winter_valley.jpg --prompt="the valley slowly transitions from summer to winter, leaves falling then snow settling over the landscape" --model_version=seedance2.0 --duration=8 --poll=180`.
