---
target: magnific/seedream-v4-5-edit
platform: magnific
syntax: natural           # tags | natural | hybrid
max_len: 600            # доки: prompt до 4096 символов, но не тег-суп
negative: false
refs: multi(5)           # reference_images: 1-5 картинок (base64 или публичный URL)
updated: 2026-07-06
sources: [docs.magnific.com/api-reference/text-to-image/post-seedream-v4-5-edit, magnific.com/ai/docs/image-ai-models]
---
# Как писать промпт для Magnific Seedream 4.5 Edit (`POST /v1/ai/text-to-image/seedream-v4-5-edit`)

Контекст: Seedream 4.5 Edit — модель с **«strong character control and multi-image fusion, up to 4K»** (по каталог-странице площадки) — рабочая лошадка для сшивки нескольких референсов в одну сцену: **основной кандидат на «лицо + локация» финалы вместо заблокированного Nano Banana** (Gemini-403, см. состояние проекта). Асинхронный API: `task_id` → `status: CREATED|IN_PROGRESS|COMPLETED|FAILED` → `generated: [url, ...]`.

**Расхождение с лимитом Hermes-инструмента:** бриф проекта описывает `images_generate` у Hermes как «референсы до 12» — это потолок MCP-обёртки в целом (по всем моделям), а не именно этой модели. Сама Seedream-4.5-edit по доке принимает **1-5** `reference_images` — если передать больше 5 через общий MCP-инструмент, лишние, вероятно, будут проигнорированы или вызовут ошибку конкретно для этой модели; не рассчитывай на 12 при выборе `model: seedream-v4-5-edit`.

## Структура промпта

`prompt` — «Text description of the image you want to generate», до 4096 символов. Дока прямо советует: **«Be specific about visual details, composition, and style»**. Пиши связным естественным текстом (как для Nano), не списком тегов: субъект+атрибуты → действие/поза → окружение → композиция/план → стиль/свет.

**Явной синтаксической схемы для адресации «какая деталь из какого референса» дока не даёт** (в отличие от официального гайда Nano/Gemini) — это не подтверждённая площадкой возможность, а перенесённая best-practice из мира multi-ref редактирования. Дока лишь говорит, что модель **«preserves subject details, lighting, and color tone»** между референсами. Раз явного протокола нет — работай защитно и избыточно: называй референсы порядково словами (`the person in the first reference image`, `the interior from the second reference image`) и дублируй ключевые визуальные признаки текстом, а не полагайся только на то, что модель «поймёт» порядок сама.

## Параметры

| Параметр | Тип/диапазон | Default | Комментарий |
|---|---|---|---|
| `prompt` | string, ≤4096 симв. | — | обязателен |
| `reference_images` | массив, 1-5 изображений | — | base64 или публичный URL; мин. 256×256px, макс. 10MB, JPG/PNG |
| `aspect_ratio` | `square_1_1, widescreen_16_9, social_story_9_16, portrait_2_3, traditional_3_4, standard_3_2, classic_4_3, cinematic_21_9` | `square_1_1` | `cinematic_21_9` — под широкоформатный кино-кадр Lion Films |
| `seed` | int 0-4294967295 | — | воспроизводимость |
| `enable_safety_checker` | bool | true | фильтр контента; в доке не указано, что его можно жёстко отключить всегда — считать по умолчанию включённым |
| `webhook_url` | URI | — | асинхронное уведомление |

`guidance_scale` в документации этого эндпоинта **не встречается** — не указывай его в вызове, не выдумывай.

## Особенности площадки

Кредиты: `simulate_cost` перед генерацией — мульти-референс/4K дороже одиночного t2i. Загрузка: локальные файлы для `reference_images` идут флоу `creations_request_upload` → PUT → `creations_finalize_upload`; `creations_upload_image` берёт только http(s)-URL. Полное описание (кредиты/upload/circuit-breaker) — в `_catalog.md`.

## Типовые фейлы

- **Больше 5 референсов** — площадка ограничивает эту модель пятью; если бриф/раскадровка даёт 6+ фото (лицо + локация + реквизит + референс-поза + мудборд...), заранее выбери 5 самых важных, а не надейся, что лишние тихо отбросятся предсказуемым образом.
- **«Плывущая» идентичность без явной ordinal-привязки** — если промпт говорит `keep her face` без указания «from the first image» при 2+ референсах, модель может не понять, чьё лицо сохранять (по аналогии с любой multi-ref моделью; дока не документирует протокол разрешения этой неоднозначности, поэтому не полагайся на неявное угадывание).
- **Смешивание атрибутов референсов без привязки** — `woman, café, red dress` без указания источника каждой детали — детали «текут» между референсами так же, как в SDXL при 2+ персонажах; разделяй явно: «женщина с первого фото», «интерьер со второго фото».
- **Тег-суп вместо связной фразы** — модель ориентирована на текстовое описание (`prompt` — «description»), а не на список тегов через запятую; конкретные фразы держат композицию лучше голых существительных.
- **Расчёт на `guidance_scale`** — параметра нет в этом эндпоинте; если нужен более строгий/более творческий баланс промпт-vs-референс, регулируй это словами в самом промпте (`closely following the reference's exact pose` vs `loosely inspired by`), не числовым параметром.

## Примеры «задача → плохо → хорошо»

**1.** Задача (RU, 2 референса): «взять актёра с фото 1, поместить в интерьер кафе с фото 2, сохранить лицо»
- Плохо: `man, café interior, sitting at table, keep face, photorealistic, high quality` — тег-суп без глагола-инструкции и без ordinal-привязки: не сказано, из какого референса человек, из какого интерьер и чьё лицо сохранять — детали «потекут» между источниками.
- Хорошо: `Place the man from the first reference image sitting at a window table inside the café interior from the second reference image. Keep his exact facial features, hair, and skin tone unchanged from the first image, and match the café's warm afternoon lighting from the second image.`
- Параметры: `reference_images: [actor.jpg, cafe_interior.jpg]`, `aspect_ratio: widescreen_16_9`.

**2.** Задача (3 референса): «персонаж + костюм + локация, кинематографично»
- Плохо: `Cinematic wide shot of the man in the outfit in the village at dusk, don't change his face, no wrong colors on the jacket` — референсы не адресованы порядково («the man», «the outfit» — какие именно?), «don't/no» — негатив-формулировки при отсутствующем negative-поле.
- Хорошо: `Using the man from the first reference image as the subject, the outfit from the second reference image as his clothing, and the mountain village street from the third reference image as the setting, create a cinematic wide shot of him walking through the village at dusk. Keep his facial features and body proportions from the first image, and match the outfit's exact colors and textures from the second image.`
- Параметры: `reference_images: [face.jpg, outfit.jpg, village.jpg]`, `aspect_ratio: cinematic_21_9`.

**3.** Задача (1 референс, чистое редактирование без сшивки): «поменять время суток на закатное, не трогая композицию»
- Плохо: `Golden hour sunset scene` + `guidance_scale: 8` — не сказано, что композицию/позу сохранить (модель пересоберёт сцену заново), плюс несуществующий для этого эндпоинта параметр `guidance_scale`.
- Хорошо: `Keep the exact same composition, subject position, and camera angle as the reference image, but change the lighting to a warm golden-hour sunset with long shadows.`
- Параметры: `reference_images: [source.jpg]`, `seed` тот же, что и прошлый прогон, если нужна повторяемость.

**4.** Задача (RU, 4 референса — реквизит continuity): «герой с фото 1, в куртке с фото 2, держит реквизит с фото 3, на фоне локации с фото 4»
- Плохо: `woman, leather jacket, vintage camera, rooftop, dusk, cinematic, preserve identity` — четыре источника свалены в один список тегов без указания, что откуда: модель вольна взять куртку «по мотивам», а лицо усреднить.
- Хорошо: `Combine the woman from the first reference image, the leather jacket from the second reference image, the vintage camera prop from the third reference image, and the rooftop skyline from the fourth reference image into one cinematic scene: she stands on the rooftop at dusk, wearing the jacket exactly as shown, holding the camera. Preserve her facial features from the first image and the jacket's texture and color from the second image.`
- Параметры: `reference_images: [4 файла]`, `aspect_ratio: cinematic_21_9`, `enable_safety_checker: true`.

**5.** Задача (RU, 5 референсов — предел модели): «сцена на пять элементов: герой, героиня, локация, реквизит, референс-поза»
- Плохо: передать 7 референсов (герой, героиня, локация, реквизит, поза, мудборд света, мудборд цвета) «на всякий случай» — модель принимает максимум 5; лишние отбросятся непредсказуемо или вызовут ошибку, а какие именно — неизвестно.
- Хорошо: `Using the man from the first reference image and the woman from the second reference image as the two subjects, place them in the diner interior from the third reference image, both seated at the counter holding the vintage radio prop from the fourth reference image, matching the sitting pose shown in the fifth reference image. Preserve both subjects' facial features exactly as shown in their respective source images.`
- Параметры: `reference_images: [5 файлов — это максимум модели]`, `aspect_ratio: widescreen_16_9`. Свет/цвет из выкинутых мудбордов — словами в промпте, не шестым референсом.

## Когда НЕ брать эту модель

- Нужна **только** точечная правка одного уже готового кадра без сшивки нескольких источников — дешевле и предсказуемее `flux-kontext-pro` (инструкция-редактирование одного `input_image`).
- Нужен **чистый фотореализм** без референсов вообще, с тонким контролем движка/детализации — `mystic` даёт больше рычагов (`engine`, `creative_detailing`, `hdr`), которых у Seedream в этом эндпоинте нет.
- Нужно **видео** — это t2i/edit-модель, для оживления кадра смотри `kling-v2-5-pro`.
