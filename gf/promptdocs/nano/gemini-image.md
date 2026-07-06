---
target: nano/gemini-image
platform: nano
syntax: natural           # tags | natural | hybrid
max_len: 500            # ориентир длины промпта в токенах
negative: false
refs: multi(4)           # none | single | multi(N)
sources: [everyinc/compound-engineering-plugin@ce-gemini-imagegen, johnlindquist/claude@gemini-image, google/ai.google.dev@image-generation, google/deepmind@nano-banana-prompt-guide, google/cloud-blog@ultimate-prompting-guide-nano-banana]
updated: 2026-07-06
---
# Как писать промпт для Nano Banana (Gemini image, `gemini-3-pro-image`)

Контекст: локальный Express-сервер («Nitro Banana») зовёт Gemini image generation через `/api/gemini`, action всегда `edit` (с рефами или без). Синтаксис — **естественный язык**: связный абзац на английском, как инструкция человеку, а не список тегов через запятую (тег-суп типа `woman, red dress, city, night, cinematic` — противоположность тому, что здесь нужно). До 4 референс-изображений (`refs: multi(4)` — ограничение нашего сервера, у самой модели лимит выше, но у нас жёсткий потолок 4). Aspect ratio передаётся отдельным параметром вызова (`aspect="9:16"` и т.п.) — **не пиши соотношение сторон словами в тексте промпта** ("16:9", "square format", "vertical") и не указывай разрешение/мегапиксели. Негативного промпта нет: нежелательное всегда описывается позитивным перефразом (см. секцию ниже).

## Структура промпта

Промпт — один связный абзац (можно 2-3 предложения), собранный из смысловых блоков в таком порядке, но без явных разделителей-тегов — блоки сливаются в естественную речь:

1. **Действие/намерение первым словом-глаголом**, если задача — редактирование/комбинирование, а не чистая генерация с нуля.
   Примеры зачинов: `Create...`, `Generate...`, `Using the attached photo of..., place...`, `Combine...`.
   Без явного глагола-намерения при наличии референсов модель иногда отвечает текстом вместо картинки или путает, что именно редактировать.
2. **Субъект** — кто/что, с конкретными атрибутами.
   Не «a woman», а «a woman in her 30s with short auburn hair, wearing a tailored navy blazer».
   Материальность важнее общих слов: не «armor», а «ornate elven plate armor etched with silver leaf patterns»; не «coffee mug», а «minimalist matte ceramic coffee mug».
3. **Действие/поза** — что субъект делает, как расположен в кадре (`sitting at a window table`, `mid-stride, looking over her shoulder`).
4. **Место/окружение** — где происходит, время суток, погода, атмосфера.
5. **Композиция и план** — план (`medium shot`, `close-up`, `wide-angle shot`, `45-degree angle`, `low-angle perspective`).
   Это фотографический/киношный язык, не абстрактные слова вроде «хороший кадр».
6. **Стиль/свет/камера последними** — художественный медиум, схема света, техника съёмки.
   Медиум: `photorealistic`, `watercolor painting`, `retro-futuristic illustration`.
   Свет: `three-point softbox setup`, `golden hour backlight`, `chiaroscuro lighting with harsh contrast`.
   Камера: `shot on Fujifilm, shallow depth of field f/1.8`, `35mm film grain`, `macro lens`.

Длина: короткий промпт (одно предложение) тоже даёт валидную картинку, но контроль над результатом растёт с детализацией — добавляй детали постепенно, а не сразу максимум. Ориентир — до ~500 токенов (`max_len`), обычно достаточно 40-90 слов на одну генерацию; больше нужно редко и почти никогда для одного кадра без референсов.

**Текст в кадре:** если нужна надпись — бери желаемые слова в кавычки и описывай шрифт словами (не техническим именем шрифта): `render the word "GLOW" in a bold, flowing script font` лучше, чем «Helvetica». Для локализации — сформулируй промпт на одном языке, но явно укажи целевой язык и точный переведённый текст в кавычках. Пример: `render the sign text in Russian: "ОТКРЫТО"`.

## Параметры (справочно — за пределы промпт-текста)

Aspect ratio и resolution — это НЕ часть текста промпта, это отдельные аргументы вызова (`aspect`, у нашего сервера дефолт `9:16`). Держи их в голове при формулировке композиции (план кадра должен логически подходить под ориентацию), но не проговаривай числами внутри промпта.

| Параметр | Где живёт | Комментарий |
|---|---|---|
| Aspect ratio | аргумент `aspect` вызова `gf_generate_final` | допустимые значения см. `VALID_ASPECTS` в `gf/backends/nano.py`: `9:16, 16:9, 1:1, 3:4, 4:3` — модель поддерживает больше вариантов, но наш сервер разрешает только эти пять |
| Referenсы | аргумент `refs` (список путей до 4 файлов) | PNG/JPEG/WEBP; порядок в списке = порядок, в котором на них ссылается промпт |
| Resolution | не настраивается с нашей стороны | сервер всегда просит `imageSize: "1K"` — не проси в промпте "4k"/"8k"/"high resolution", это ничего не изменит на нашем пути вызова |
| Seed | не поддерживается | Nitro-сервер не принимает seed — воспроизводимость только через явное описание (детальный промпт + референсы) |

## Референсы

До 4 изображений на вызов, каждое из массива `refs` — модель видит их в переданном порядке. Ссылайся на них **порядково**, не по содержимому, которое модель ещё не «видела» твоими глазами: `the woman from the first reference image`, `the location from the second reference image`, `the object in the third image`. Не пиши "the reference image" в единственном числе, если референсов больше одного — модель не поймёт, какой из них.

**Сохранение identity** (лицо/персонаж не должно "плыть"): указывай явно, что нужно сохранить неизменным — `keeping her exact facial features, hair color, and expression unchanged` — и дублируй ключевые визуальные признаки словами, а не полагайся только на референс: `the woman with brown hair, blue eyes, and a neutral expression from the first image`. Это не замена референсу, а подстраховка: словесное описание держит identity, даже если модель на конкретном шаге недовзвесила картинку.

**Комбинирование лицо+локация** (типовой кейс multi-ref: 1 фото персонажа + 1 фото места, иногда третий референс — референс позы/одежды): формула — `[ссылка на референс-1] as the subject, [ссылка на референс-2] as the setting, [явная инструкция как совместить]`. Пример: `Using the woman from the first reference image and the café interior from the second reference image, place her sitting at the window table, keeping her exact facial features and clothing style unchanged while matching the café's warm afternoon lighting.` Не смешивай атрибуты референсов без привязки («woman, café, sitting» без указания, из какого референса что) — при 2+ референсах модель, как и SDXL, может «перетекать» деталями между источниками, если не сказано явно, что откуда.

## Чего избегать и как (без негатива)

У Nano нет negative prompt — то, что не нужно, всегда переформулируется в позитивное описание желаемого состояния:

| Не пиши (негатив) | Пиши (позитив) |
|---|---|
| `no cars on the street` | `an empty street` |
| `without wrinkles` | `smooth, flawless skin` |
| `not blurry` | `sharp focus, crisp details` |
| `no text in the image` | (просто не упоминай текст вообще — не проси и не запрещай) |
| `don't change the background` | `keep the background exactly as in the reference image` |

Правило: если тянет написать «без X» или «не X» — останови и спроси себя, каким должно быть состояние *вместо* X, и опиши это состояние.

## Словарь: свет / камера / стиль (для быстрой сборки промпта)

- **Свет:** `golden hour backlight`, `soft diffused window light`, `three-point softbox setup`, `chiaroscuro lighting with harsh contrast`, `rim lighting`, `overcast, even daylight`.
- **Камера/план:** `medium shot`, `close-up`, `wide-angle shot`, `low-angle perspective`, `45-degree angle`, `macro lens`, `shallow depth of field (f/1.8)`.
- **Плёнка/пост:** `shot on Fujifilm, authentic color science`, `1980s color film, slightly grainy`, `cinematic color grading with muted teal tones`.
- **Медиум/стиль:** `photorealistic`, `kawaii-style sticker illustration`, `retro-futuristic illustration`, `watercolor painting`, `editorial fashion photography`.

Используй это как затравку, а не готовый список — конкретика задачи (какой именно свет/план нужен по смыслу сцены) важнее механической вставки модного термина.

## Типовые фейлы

- **Отсутствие глагола-намерения при референсах** — промпт вида «a woman at a café» без `create`/`using... place...` при наличии картинок-референсов иногда трактуется моделью как вопрос/описание, а не команда генерировать — начинай с явного действия.
- **Aspect ratio словами в тексте** — если написать «vertical 9:16 shot» в самом промпте, это как минимум избыточно (параметр `aspect` уже это задаёт отдельно), а на некоторых генерациях создаёт противоречие с реальным переданным aspect и путает композицию. Про план/кадрирование (`close-up`, `wide shot`) — можно и нужно, это не то же самое, что соотношение сторон.
- **Тег-суп вместо связного текста** — список голых существительных через запятую (`woman, city, night, neon, cinematic`) хуже держит композицию и identity референсов, чем та же информация в виде связной фразы. Это модель другого типа (multimodal LLM, не CLIP-энкодер SDXL) — она разбирает естественный язык лучше, чем теги, и упор на теги ничего не даёт, только теряет качество формулировки.
- **Референс без порядковой привязки при 2+ референсах** — «keep her face the same» без указания «from the first image» — модель может не понять, чьё лицо и с какого референса сохранять, если референсов несколько.
- **Негативная формулировка по привычке из SDXL-мира** — писать `no watermark, no text, no blurry` в конце промпта не работает как negative prompt (Nano его не парсит отдельным полем) и в тексте просто добавляет шум/потенциально даже наводит модель на упомянутые объекты («efекt Стрейзанд»: упоминание «no text» иногда провоцирует появление текста, потому что слово «text» попало в контекст).
- **Слишком общие материалы/объекты** — «a jacket», «a car» без конкретики дают усреднённый, невыразительный результат; всегда добавляй материал/бренд-нейтральные детали (`a worn brown leather jacket with a frayed collar`).

## Примеры «задача → плохо → хорошо»

**1.** Задача (RU): «Портрет пожилой женщины у окна, мягкий дневной свет, фотореалистично»
- Плохо: `old woman, window, daylight, photorealistic, portrait, 4k, no wrinkles removed, not cartoon`
- Хорошо: `Create a photorealistic close-up portrait of an elderly woman with silver hair pulled into a loose bun, sitting by a large window. Soft, diffused daylight falls across her face from the side, highlighting the fine texture of her skin. Shallow depth of field, shot on a portrait lens at f/1.8, warm and gentle color grading.`

**2.** Задача: product shot of a ceramic mug (без референсов)
- Плохо: `ceramic mug, studio, nice lighting, product photo, no shadows, no clutter`
- Хорошо: `A high-resolution studio product photograph of a minimalist matte black ceramic coffee mug resting on a warm grey stone surface. A three-point softbox setup gives even, soft lighting with a gentle highlight along the rim. Clean, uncluttered background, macro lens, commercial photography style.`

**3.** Задача (multi-ref, 2 референса): «взять человека с первого фото и поместить в интерьер кафе со второго фото, сохранить лицо»
- Плохо: `woman, café, sitting, keep face, nice lighting` (не указано, из какого референса что, нет глагола-инструкции)
- Хорошо: `Using the woman from the first reference image and the café interior from the second reference image, place her sitting at the window table with a cup of coffee, keeping her exact facial features, hair color, and clothing unchanged, while matching the café's warm afternoon window light.`

**4.** Задача: постер с текстом (typography-кейс)
- Плохо: `poster, bold text "SUMMER SALE", nice font, no blurry text, not distorted`
- Хорошо: `Create a modern minimalist poster with a solid deep-orange background. Render the words "SUMMER SALE" in a bold, clean sans-serif font, centered and filling most of the frame. Below it, in a smaller thin sans-serif font, render the text "Up to 50% Off".`

**5.** Задача (RU, multi-ref, 3 референса): «персонаж с фото 1 в костюме с референса 2, на фоне локации с референса 3, стиль кинематографичный»
- Плохо: `character, costume, location, cinematic, high quality, keep identity`
- Хорошо: `Using the man from the first reference image as the subject, the outfit from the second reference image as his clothing, and the mountain village from the third reference image as the setting, create a cinematic wide shot of him walking through the village street at dusk. Keep his exact facial features and body proportions unchanged, dress him in the outfit's exact colors and textures, and match the warm, muted color grading of the village photo.`
