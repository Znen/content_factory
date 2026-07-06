---
target: magnific/mystic
platform: magnific
syntax: natural           # tags | natural | hybrid
max_len: 200            # ориентир — доки называют prompt "short text", не абзац
negative: false
refs: multi(2)           # два РАЗНЫХ именованных слота (structure_reference + style_reference), не N взаимозаменяемых картинок
updated: 2026-07-06
sources: [docs.magnific.com/api-reference/mystic/mystic, docs.magnific.com/api-reference/mystic/post-mystic, magnific.com/blog/freepik-mystic, magnific.com/ai/docs/image-ai-models]
---
# Как писать промпт для Magnific Mystic (`POST /v1/ai/mystic`)

Контекст: Mystic — флагманская фотореалистичная t2i-модель площадки Magnific (эксклюзив, не отдаётся сторонним хостерам). Асинхронный API: отправил промпт → получил `task_id` → опрашивай `GET /v1/ai/mystic/{task-id}` или жди `webhook_url`; генерация 10-90 сек в зависимости от `resolution`. Hermes зовёт площадку напрямую через облачный MCP `mcp.magnific.com` (`images_generate` с выбором модели) — **имена полей в MCP-обёртке могут отличаться от сырых REST-полей ниже** (это доки Freepik REST API, не спека MCP-инструмента); если вызов вернёт ошибку валидации параметра — не считай этот паспорт неверным, свериться по факту ответа инструмента.

## Структура промпта

`prompt` документация описывает как **«short text that describes the image you want to generate»** — короткий связный текст на естественном языке, не тег-суп и не длинный абзац (в отличие от Nano). Держи 1-3 предложения: субъект+действие → окружение/свет → стиль/план. Negative-поля нет вообще (не `negative_prompt: false` из-за отсутствия в доке, а именно отсутствующий параметр) — нежелательное описывай позитивным перефразом, как в Nano.

**Важно про идентичность лица:** Mystic — НЕ инструмент «вставь именно это лицо в именно эту локацию» (в отличие от Nano/Seedream). `structure_reference` и `style_reference` — это модификаторы композиции/эстетики, а не face-swap/identity-lock. Если задача — «лицо с фото А в интерьере с фото Б», это к `seedream-v4-5-edit` (см. `_catalog.md`), не к Mystic.

## Референсы

Два независимых слота (base64-изображение), можно использовать любой один или оба:
- **`structure_reference`** + `structure_strength` (0-100, default 50) — «влияет на форму финального изображения»: композиция, поза, силуэт. Держит layout референса, не его цвет/текстуру.
- **`style_reference`** + `adherence` (0-100, default 50) — «влияет на эстетику», названо в доках «most powerful tool» — сильнее structure_reference по влиянию на итог. `adherence` — баланс верности промпту vs верности стилю референса; ниже — точнее промпт, выше — точнее стиль (и меньше артефактов при высоком значении, по доке).
- Дока прямо рекомендует: «Send reference images via URL whenever possible. Higher quality reference images produce better style and structure transfers.» — параметр типизирован как base64 в схеме, но рекомендация про URL намекает на поддержку и того, и другого; не считай это противоречием, проверяй по факту вызова.

## Параметры

| Параметр | Диапазон/enum | Default | Комментарий |
|---|---|---|---|
| `resolution` | `1k, 2k, 4k` | `2k` | выше — дороже и дольше (10-90с) |
| `aspect_ratio` | `square_1_1, classic_4_3, traditional_3_4, widescreen_16_9, social_story_9_16, smartphone_horizontal_20_9, smartphone_vertical_9_20, standard_3_2, portrait_2_3, horizontal_2_1, vertical_1_2, social_5_4, social_post_4_5` | `square_1_1` | много вариантов — выбирай под финальный носитель кадра |
| `model` | `zen, flexible, fluid, realism, super_real, editorial_portraits` | `realism` | стилевой движок Mystic; `editorial_portraits`/`super_real` — под кино-стилистику и портреты Lion Films |
| `engine` | `automatic, magnific_illusio, magnific_sharpy, magnific_sparkle` | `automatic` | пост-обработка резкости/детализации; `automatic` — безопасный дефолт |
| `creative_detailing` | 0-100 | 33 | деталь на пиксель; выше — риск «пережаренной», неестественной картинки |
| `hdr` | 0-100 | 50 | детальность; выше — риск «AI look» (пере-чёткость) |
| `fixed_generation` | bool | false | `true` — одинаковый результат при одинаковых настройках (воспроизводимость) |
| `filter_nsfw` | bool | true | **нельзя отключить** — фильтр всегда активен |

**Стили/персонажи (LoRA через `/v1/ai/loras`):**
- `characters` (массив, max 1): `{id, strength}` (strength 0-200, default 100) — обращение в тексте промпта через `@character_name` или `@character_name::strength`.
- `styles` (массив, max 1): `{name, strength}` (та же шкала) — готовый стиль-пресет.
- `colors` (массив, 1-5): `{color: "#RRGGBB", weight: 0.05-1.0}` — прямой контроль палитры без слов в промпте.

## Особенности площадки

Кредиты: перед генерацией на `4k`/тяжёлым `engine` — сначала `simulate_cost`, не гадать по ощущению. Локальные файлы (кандидаты в `structure_reference`/`style_reference`) НЕ грузятся напрямую — путь `creations_request_upload` → PUT → `creations_finalize_upload` (`creations_upload_image` принимает только http(s)-URL). Полное описание кредитов/upload-флоу/circuit-breaker — в `_catalog.md`.

## Типовые фейлы

- **LoRA молча игнорируется без ошибки.** `characters`/`styles` **не применяются**, если `model` ∈ `{fluid, flexible, super_real, editorial_portraits}` ИЛИ если задан `structure_reference`/`style_reference` — и API **не вернёт ошибку** на это сочетание (по доке — «will not return errors for incompatible combinations»). Если персонаж-LoRA не проявился в результате — проверь именно эту комбинацию первым делом, а не промпт.
- **`hdr`/`creative_detailing` на максимум** — типичный провал: «пере-хрустящая», искусственно резкая картинка вместо фотореализма. Для фотореализма Lion Films держи оба ближе к дефолту (30-60), не к 90-100.
- **Ожидание face-identity от `style_reference`** — style_reference задаёт настроение/цвет/фактуру, а не «то самое лицо»; если лицо «поплыло» относительно референса — это ожидаемое поведение модели, не баг промпта, нужна другая модель (Seedream) для этой задачи.
- **`filter_nsfw` блокирует легитимный контент** (купальники, батальные сцены, медицинские сюжеты) без возможности отключить — переформулируй эвфемизмом (`swimwear` вместо описания тела крупным планом, `battle aftermath` вместо explicit gore) вместо повторных попыток с тем же промптом.
- **`adherence` слишком низкий при заданном `style_reference`** — промпт теряет вес, результат «плывёт» к референсу сильнее, чем нужно по тексту задачи; поднимай `adherence`, если стиль референса перебивает конкретику промпта.

## Примеры «задача → плохо → хорошо»

**1.** Задача (RU): «Портрет пожилого рыбака на закате, кинематографично, крупный план»
- Плохо: `masterpiece, best quality, old fisherman, sunset, cinematic, 8k, (weathered face:1.3), no blur, no cartoon` — SDXL-привычки: quality-теги и веса в скобках здесь не парсятся, «no blur/no cartoon» — негатив-формулировка при отсутствующем negative-поле, тег-суп вместо короткой связной фразы.
- Хорошо: `A weathered elderly fisherman with a grey beard and deep sun-worn wrinkles, standing on a wooden pier at golden hour, warm rim light from the setting sun, close-up portrait, cinematic mood.`
- Параметры: `model: editorial_portraits`, `aspect_ratio: portrait_2_3`, `resolution: 2k`.

**2.** Задача: рекламный кадр парфюма, студийный свет (без референсов)
- Плохо: тот же текст промпта, но `creative_detailing: 95, hdr: 90` — выкрученные детализация/hdr дают «пере-хрустящий AI-look» вместо чистого продуктового фотореализма; типовой фейл параметров, а не текста.
- Хорошо: `A frosted glass perfume bottle with a brushed gold cap on a black marble surface, soft diffused studio lighting with crisp highlights, minimalist commercial product photography.`
- Параметры: `model: realism`, `aspect_ratio: square_1_1`, `creative_detailing: 45`.

**3.** Задача: сохранить композицию черновика (ComfyUI-скетч позы), но дать кино-фактуру
- Плохо: `Exact same pose and composition as the reference image: a knight standing in a cathedral, cinematic` — «как на референсе» словами не работает: текст промпта не адресует референс, удержание композиции — работа `structure_reference` + `structure_strength`, а не формулировки.
- Хорошо: `A knight standing in a ruined cathedral, dust particles in shafts of light, dramatic chiaroscuro lighting, cinematic film still.`
- Параметры: `structure_reference: <черновик>`, `structure_strength: 65`, `model: super_real`.

**4.** Задача: персонаж с фирменным LoRA-пресетом Lion Films в новой сцене
- Плохо: `@hero_lora_id walking through a neon alley at night` + `model: super_real`, `style_reference: <мудборд>` — LoRA молча игнорируется и при `super_real`, и при заданном `style_reference` (API не вернёт ошибку — по доке «will not return errors for incompatible combinations»): персонаж просто не появится, и непонятно почему.
- Хорошо: `@hero_lora_id::120 walking through a rain-soaked neon-lit alley at night, cinematic color grading, wide shot.`
- Параметры: `characters: [{id: "hero_lora_id", strength: 120}]`, `model: flexible` (LoRA-совместимый), без `structure_reference`/`style_reference`.

**5.** Задача (RU): «Пейзаж локации в фирменной цветовой палитре бренда (тёмно-синий + золото)»
- Плохо: `A mountain valley at dawn, brand colors #0B1F3A and #C9A24B only, no other colors, no oversaturation` — hex-коды в тексте промпта не парсятся (для палитры есть параметр `colors`), «no other colors / no oversaturation» — мёртвая негатив-формулировка.
- Хорошо: `A misty mountain valley at dawn, cinematic wide establishing shot, muted atmospheric color grading.`
- Параметры: `colors: [{color:"#0B1F3A", weight:0.8}, {color:"#C9A24B", weight:0.6}]`, `model: realism`, `resolution: 4k`.
