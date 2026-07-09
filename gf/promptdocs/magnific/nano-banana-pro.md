---
target: magnific/nano-banana-pro
platform: magnific
syntax: natural           # tags | natural | hybrid
max_len: 500            # обычно 40-90 слов на кадр; больше нужно редко
negative: false
refs: multi              # reference_images: 0-4 (t2i без рефов ИЛИ multi-ref сшивка)
updated: 2026-07-09
sources: [google/deepmind@nano-banana-prompt-guide, google/ai.google.dev@image-generation, magnific.com/api-reference/text-to-image/nano-banana-pro]
---
# Как писать промпт для Magnific Nano Banana Pro (`POST /v1/ai/text-to-image/nano-banana-pro`)

Контекст: **Nano Banana Pro** — модель семейства Google Gemini image, доступная на Magnific REST (verified live 2026-07-09). Это тот же «характер», что и локальный Nano (`nano/gemini-image`), но через заводской Magnific-бэкенд, а не заблокированный Nitro/Gemini-403 — **рабочий путь для финалов**. Умеет и чистый t2i (без референсов), и multi-ref сшивку до **4** изображений (лицо+локация, как seedream). Асинхронный API идентичен другим Magnific-моделям: `task_id` → `status: CREATED|IN_PROGRESS|COMPLETED|FAILED` → `generated: [url, ...]` (~6с генерация).

**⚠️ ГЛАВНОЕ ОТЛИЧИЕ ПО ASPECT:** у nano-banana-pro `aspect_ratio` — в **ОБЫЧНОМ формате** (`"9:16"`, `"16:9"`, `"1:1"`), **НЕ** в magnific-enum (`square_1_1`, `widescreen_16_9`), который используют `mystic`/`seedream`/`flux`. Формат aspect на Magnific зависит от модели — для этой модели пиши `"9:16"`-стиль. Как и везде: aspect — отдельный параметр вызова, **не проговаривай соотношение сторон словами в тексте промпта**.

## Структура промпта

Синтаксис — **естественный язык**: связный абзац на английском (как инструкция человеку), не список тегов через запятую (тег-суп `woman, red dress, city, night, cinematic` — противоположность нужному). Собирай из смысловых блоков в этом порядке, но сливая их в речь, без тег-разделителей:

1. **Действие/намерение первым глаголом** — если задача редактирование/сшивка референсов: `Create...`, `Generate...`, `Using the first reference image..., place...`, `Combine...`. Для чистого t2i с нуля глагол-намерение не обязателен, но помогает.
2. **Субъект** — кто/что, с конкретными атрибутами. Не «a woman», а «a woman in her 30s with short auburn hair, wearing a tailored navy blazer». Материальность важнее общих слов: не «armor», а «ornate elven plate armor etched with silver leaf patterns».
3. **Действие/поза** — что субъект делает, как расположен в кадре (`sitting at a window table`, `mid-stride, looking over her shoulder`).
4. **Место/окружение** — где, время суток, погода, атмосфера.
5. **Композиция и план** — киношный/фотоязык (`medium shot`, `close-up`, `wide-angle shot`, `low-angle perspective`, `45-degree angle`), НЕ абстрактное «хороший кадр» и НЕ соотношение сторон.
6. **Стиль/свет/камера последними** — медиум (`photorealistic`, `watercolor painting`), свет (`golden hour backlight`, `three-point softbox setup`, `chiaroscuro`), камера (`shallow depth of field f/1.8`, `35mm film grain`, `macro lens`).

Длина: короткий промпт тоже валиден, но контроль растёт с детализацией — добавляй детали постепенно. Ориентир — до ~500 токенов (`max_len`), обычно 40-90 слов на кадр.

**Текст в кадре:** нужные слова — в кавычки, шрифт описывай словами: `render the word "GLOW" in a bold, flowing script font`. Локализация — явно укажи язык и точный текст: `render the sign text in Russian: "ОТКРЫТО"`.

## Референсы (multi-ref, 0-4)

`reference_images` — **опциональны** (0 рефов = чистый t2i; поле просто не передаётся). До **4** изображений (base64 в теле; лимит завода для этой модели), модель видит их в переданном порядке. Ссылайся **порядково**: `the woman from the first reference image`, `the location from the second reference image`. Не пиши «the reference image» в единственном числе при 2+ референсах.

**Сохранение identity** (лицо/персонаж не «плывёт»): указывай явно, что сохранить, и дублируй ключевые признаки словами — `keeping her exact facial features, hair color, and expression unchanged` + `the woman with brown hair, blue eyes, and a neutral expression from the first image`. Словесное описание страхует identity, если модель на шаге недовзвесила картинку.

**Комбинирование лицо+локация** (типовой кейс: 1 фото персонажа + 1 фото места, иногда 3-й реф — поза/одежда): формула — `[ссылка на референс-1] as the subject, [ссылка на референс-2] as the setting, [явная инструкция как совместить]`. Не смешивай атрибуты референсов без привязки — при 2+ референсах детали «текут» между источниками, если не сказано явно, что откуда.

## Чего избегать и как (без негатива)

Негативного промпта нет — нежелательное всегда позитивным перефразом:

| Не пиши (негатив) | Пиши (позитив) |
|---|---|
| `no cars on the street` | `an empty street` |
| `without wrinkles` | `smooth, flawless skin` |
| `not blurry` | `sharp focus, crisp details` |
| `no text in the image` | (просто не упоминай текст вообще) |
| `don't change the background` | `keep the background exactly as in the first reference image` |

Правило: тянет написать «без X» — спроси, каким должно быть состояние *вместо* X, и опиши его.

## Параметры

| Параметр | Тип/диапазон | Комментарий |
|---|---|---|
| `prompt` | string, ≥2 симв., ОБЯЗАТЕЛЕН | связный текст, не тег-суп |
| `reference_images` | массив base64, 0-4, ОПЦИОНАЛЬНЫ | 0 = t2i; порядок в списке = порядок ссылок в промпте; PNG/JPG/WEBP |
| `aspect_ratio` | ОПЦИОНАЛЕН, **обычный формат** | enum: `1:1, 2:3, 3:2, 4:3, 3:4, 5:4, 4:5, 16:9, 9:16, 21:9`. ⚠️ НЕ magnific-enum (`square_1_1`…) — это отличие nano-banana-pro; передаётся параметром, не словами в тексте |

`seed`/`guidance_scale`/`negative_prompt` в этом эндпоинте не подтверждены — не выдумывай; управляй результатом словами промпта и референсами.

## Особенности площадки

Кредиты: `simulate_cost` перед генерацией (multi-ref дороже t2i). Референсы идут **прямо base64 в теле** запроса — отдельный upload-флоу не нужен (в отличие от старого предположения по seedream). Полное описание кредитов/circuit-breaker — в `_catalog.md`.

## Типовые фейлы

- **Aspect в magnific-enum вместо обычного формата** — написать `aspect_ratio: widescreen_16_9` для nano-banana-pro: у этой модели формат `"16:9"`, enum отвергнется/не сработает. Enum — только у mystic/seedream/flux.
- **Aspect словами в тексте промпта** — `vertical 9:16 shot` в тексте избыточно (параметр `aspect` уже это задаёт) и может противоречить реальному aspect. Про план/кадрирование (`close-up`, `wide shot`) — можно, это не соотношение сторон.
- **Тег-суп вместо связной фразы** — список голых существительных держит композицию и identity хуже связного текста; это multimodal-LLM (как Gemini), не CLIP-энкодер SDXL — она разбирает естественный язык лучше тегов.
- **Референс без порядковой привязки при 2+ референсах** — `keep her face` без `from the first image`: модель не поймёт, чьё лицо и с какого рефа сохранять.
- **Негатив по привычке из SDXL** — `no watermark, no text, no blurry` не работает как negative (поля нет), только шумит и может наводить на упомянутое (эффект Стрейзанд: слово «text» провоцирует текст).
- **Слишком общие материалы/объекты** — «a jacket», «a car» дают усреднённый результат; добавляй материал/детали (`a worn brown leather jacket with a frayed collar`).

## Примеры «задача → плохо → хорошо»

**1.** Задача (RU, чистый t2i без референсов): «Портрет пожилой женщины у окна, мягкий дневной свет, фотореалистично»
- Плохо: `old woman, window, daylight, photorealistic, portrait, 4k, no wrinkles, not cartoon` — тег-суп, негатив-формулировки, разрешение словами.
- Хорошо: `Create a photorealistic close-up portrait of an elderly woman with silver hair pulled into a loose bun, sitting by a large window. Soft, diffused daylight falls across her face from the side, highlighting the fine texture of her skin. Shallow depth of field, shot on a portrait lens at f/1.8, warm gentle color grading.`
- Параметры: `reference_images: []` (t2i), `aspect_ratio: "4:5"`.

**2.** Задача (t2i, продукт): «студийный снимок керамической кружки»
- Плохо: `ceramic mug, studio, nice lighting, product photo, no shadows, no clutter, square_1_1` — тег-суп, негативы, и magnific-enum aspect (у этой модели формат `"1:1"`).
- Хорошо: `A high-resolution studio product photograph of a minimalist matte black ceramic coffee mug resting on a warm grey stone surface. A three-point softbox setup gives even, soft lighting with a gentle highlight along the rim. Clean, uncluttered background, macro lens, commercial photography style.`
- Параметры: `aspect_ratio: "1:1"`.

**3.** Задача (RU, 2 референса — лицо+локация): «взять актрису с фото 1, поместить в интерьер кафе с фото 2, сохранить лицо»
- Плохо: `woman, café, sitting, keep face, nice lighting` — не указано, из какого рефа что, нет глагола-инструкции, identity не привязана.
- Хорошо: `Using the woman from the first reference image and the café interior from the second reference image, place her sitting at the window table with a cup of coffee, keeping her exact facial features, hair color, and clothing unchanged, while matching the café's warm afternoon window light.`
- Параметры: `reference_images: [actress.jpg, cafe.jpg]`, `aspect_ratio: "16:9"`.

**4.** Задача (3 референса — персонаж+костюм+локация, кино): «герой с фото 1 в костюме с фото 2, на фоне деревни с фото 3»
- Плохо: `character, costume, location, cinematic, high quality, keep identity` — референсы не адресованы порядково, «keep identity» без деталей.
- Хорошо: `Using the man from the first reference image as the subject, the outfit from the second reference image as his clothing, and the mountain village from the third reference image as the setting, create a cinematic wide shot of him walking through the village street at dusk. Keep his exact facial features and body proportions from the first image, dress him in the outfit's exact colors and textures from the second image, and match the warm muted color grading of the village photo.`
- Параметры: `reference_images: [face.jpg, outfit.jpg, village.jpg]`, `aspect_ratio: "21:9"`.

**5.** Задача (постер с текстом, t2i): «минималистичный постер SUMMER SALE»
- Плохо: `poster, bold text "SUMMER SALE", nice font, no blurry text, not distorted` — негативы про текст (провоцируют артефакты), «nice font» вместо описания.
- Хорошо: `Create a modern minimalist poster with a solid deep-orange background. Render the words "SUMMER SALE" in a bold, clean sans-serif font, centered and filling most of the frame. Below it, in a smaller thin sans-serif font, render the text "Up to 50% Off".`
- Параметры: `aspect_ratio: "2:3"`.

## Когда НЕ брать эту модель

- Нужен **тонкий контроль движка/детализации** без референсов — `mystic` даёт `engine`/`creative_detailing`/`hdr`, которых тут нет.
- Нужна **точечная инструкция-правка одного готового кадра** — `flux-kontext-pro` (один `input_image`) предсказуемее.
- Нужно **видео** — это t2i/edit-модель; для оживления кадра `kling-v2-5-pro`.
