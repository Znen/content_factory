---
target: comfyui/sdxl-juggernaut
platform: comfyui
syntax: hybrid            # tags | natural | hybrid
max_len: 300            # ориентир длины промпта в токенах
negative: true
refs: none              # none | single | multi(N)
sources: [mckruz/comfyui-expert@comfyui-prompt-engineer, replicate/skills@prompt-images, davila7/claude-code-templates@stable-diffusion-image-generation, rundiffusion/juggernaut-xl-v9@huggingface-model-card]
updated: 2026-07-06
---
# Как писать промпт для ComfyUI / SDXL (JuggernautXL)

Контекст: чекпоинт `juggernautxl_ragnarok.safetensors` (SDXL 1.0 family), txt2img, узел `CLIPTextEncode` (positive+negative), референсов нет (`refs: none`).

## Структура промпта

Порядок сегментов, разделённых запятыми (`syntax: hybrid` — каждый сегмент это короткая natural-language фраза, а не одно слово-тег; сама последовательность сегментов фиксированная, как в тег-based промптинге):

```
{quality tags}, {субъект + действие}, {детали субъекта}, {окружение}, {стиль/жанр}, {свет}, {камера}, {доп. качество-теги}
```

1. **Quality tags первыми** — для SDXL (в отличие от FLUX) это реально работает и задаёт общий уровень детализации: `masterpiece, best quality, photorealistic` (или `cinematic film still` для не-фото стиля). Не переусердствуй — 2-3 тега, не десять.
2. **Субъект и действие** — кто/что и что делает. Называй субъект явно (`the woman in the red coat`), не местоимением — модель хуже держит контекст на местоимениях.
3. **Детали субъекта** — материалы, текстуры кожи/одежды, цвет глаз/волос, экспрессия. Конкретика бьёт общие слова: `detailed skin texture with pores, freckles` лучше, чем `realistic skin`.
4. **Окружение** — где происходит, время суток, погода.
5. **Стиль/жанр** — фотография / кино / иллюстрация; называй жанр фотографии, если нужен реализм: `architecture photography`, `product photography`, `still mid shot`.
6. **Свет** — конкретная схема, не «good lighting»: `golden hour`, `rembrandt lighting`, `rim lighting`, `soft diffused studio light`.
7. **Камера** — плёнка/объектив/техника: `shot on Kodak Portra 800`, `85mm f/1.4`, `shallow depth of field`, `tilt-shift`. Работает и на SDXL, хотя чекпоинт не «понимает» физику камеры так же глубоко, как FLUX — воспринимай как модификатор стиля.
8. **Доп. качество-теги в конце** — `8k uhd, RAW photo, film grain` — это «подпись», не структура; не растягивай.

Длина: 50-150 слов (~150-225 токенов) — medium-long диапазон для SDXL. Оба CLIP-энкодера SDXL (ViT-bigG + ViT-L) физически режут на 77 токенах на чанк; ComfyUI сам разбивает более длинный текст на чанки, но самое важное (субъект, стиль) всё равно клади в первые ~70 токенов — на случай, если чанкинг конкретной ноды не идеален.

**Веса `(word:1.2)` / `((word))`:**
- Используй для стиля, материалов, освещения, композиции — там где нужно усилить конкретный аспект без переписывания всей фразы: `(dramatic lighting:1.3)`.
- НЕ используй тяжёлые веса на анатомии/лице для одиночного персонажа без identity-метода (InstantID/PuLID/LoRA) — на JuggernautXL это обычно даёт пере-прожаренную («burnt», оверсатурированную) картинку быстрее, чем на «ванильном» SDXL, потому что чекпоинт уже сильно контрастный по дефолту.
- Множественные вложенные скобки `(((word)))` — почти всегда лишнее; если нужно больше 1.4, лучше переформулируй фразу, а не наращивай вес.

## Negative prompt

JuggernautXL/RunDiffusion прямо рекомендует **начинать с пустого или короткого негатива** и докидывать по необходимости — тяжёлый универсальный негативный блок на 30+ токенов на этом чекпоинте чаще ухудшает результат (пере-сглаживает, убирает фактуру), чем на среднем SDXL-чекпоинте.

Базовый негатив (используй как стартовый набор, не «золотой стандарт»):
```
(worst quality:1.3), (low quality:1.3), blurry, deformed, bad anatomy,
bad hands, extra fingers, missing fingers, extra limbs, watermark, text, signature
```

Докидывай по типу задачи:
- **Фотореализм** (портрет/продукт/пейзаж): `3d render, cartoon, anime, illustration, painting, cgi, plastic skin, airbrushed, oversaturated`
- **Мульти-персонажность** (2+ героя в кадре): `merged bodies, extra heads, cloned face, duplicate person`
- **Кадр с текстом/лого**: `garbled text, illegible text, extra letters` (SDXL/Juggernaut рендерит текст ненадёжно — см. «Типовые фейлы»)
- **Портрет крупным планом**: `asymmetrical eyes, cross-eyed, bad teeth, uneven pupils`

Если промпт и так короткий/простой — можно вообще не давать негатив первой итерацией и добавить только после просмотра результата (это специфично для этого чекпоинта, не общее правило SDXL).

## Параметры (рекомендации для params)

| Параметр | Значение | Комментарий |
|---|---|---|
| Разрешение (квадрат) | 1024×1024 | дефолт для соц/каталог |
| Разрешение (портрет) | 832×1216 | крупный план, персонаж в рост |
| Разрешение (пейзаж) | 1216×832 | окружение, широкий кадр |
| Steps | 30-40 | 25 — приемлемо для черновика, ниже 20 не давай |
| CFG | 4-6 (реализм) / до 7-8 (стилизация, иллюстрация) | JuggernautXL тюнен под **более низкий** CFG, чем «типовой» SDXL-совет (7-9): выше 8 стабильно даёт пере-контрастную/оверсатурированную картинку на этом чекпоинте |
| Sampler | `dpmpp_2m` или `dpmpp_2m_sde` | scheduler `karras` |
| VAE | встроенный в чекпоинт | НЕ подключай внешний VAE — двойное декодирование даёт артефакты и сдвиг цвета |
| Clip skip | не трогать (дефолт) | это в первую очередь SD1.5-концепция; для SDXL большого эффекта нет |
| Upscale (опционально) | 1.5×, denoise 0.25-0.35, 10-15 шагов | hi-res fix поверх базовой генерации, не увеличивай denoise выше 0.4 — потеряешь композицию |

## Типовые фейлы

- **Анатомия рук/пальцев** — классический SDXL-провал. Смягчается негативом (`bad hands, extra fingers`), но не убирается полностью без FaceDetailer/hand-fix прохода — это уровень workflow, не промпта; в промпте можно снизить риск, явно указав позу рук (`hands clasped together`, `hands in pockets`) вместо оставить модели додумывать.
- **Текст в кадре** — SDXL/Juggernaut рендерит текст ненадёжно (в отличие от FLUX/Ideogram). Не проси сложную типографику; если нужен короткий текст — оборачивай в кавычки (`sign that reads "OPEN"`) и закладывай на переделку/аутпейнт текста отдельно.
- **Мульти-персонажность** — при 2+ субъектах в одном промпте атрибуты «текут» между персонажами (цвет одежды/волос путается). Разделяй явно: `the man on the left wearing a blue jacket, the woman on the right wearing a red dress`, а не два набора атрибутов подряд без привязки к субъекту.
- **Переутяжелённые веса на лице/идентичности** — `(beautiful face:1.5)` без identity-метода даёт «плавленое» лицо на JuggernautXL быстрее, чем на нейтральном SDXL. Проверяй CFG в паре с весами: если и то, и другое подкручено вверх — жди пере-жар.
- **Keyword soup вместо структуры** — длинный список голых тегов без связок (`woman, red dress, city, night, neon, rain, cinematic`) хуже держит композицию, чем те же детали, оформленные фразами (`a woman in a red dress walking through a neon-lit rainy street at night`). Для этого чекпоинта работает golden mean: тег-порядок сегментов (см. «Структура»), но внутри сегмента — фраза, а не голое слово.

## Примеры «задача -> плохо -> хорошо»

**1.** Задача (RU): «Портрет пожилого рыбака на закате, кинематографично»
- Плохо: `old fisherman, sunset, cinematic, 8k, best quality, masterpiece, ultra detailed, sharp focus, trending on artstation`
- Хорошо: `masterpiece, best quality, photorealistic portrait of an elderly fisherman with weathered skin and a grey beard, deep wrinkles, salt-stained wool sweater, standing on a wooden pier at golden hour, warm rim lighting from the setting sun, shot on 85mm f/1.4, shallow depth of field, cinematic film still, film grain`

**2.** Задача: product shot of a perfume bottle
- Плохо: `perfume bottle, product photo, nice lighting, studio, luxury`
- Хорошо: `masterpiece, best quality, product photography of a frosted glass perfume bottle with a brushed gold cap, resting on a black marble surface, soft diffused studio lighting with crisp highlights and gentle shadows, minimalist background, macro lens, commercial photography`

**3.** Задача (RU): «Ночной городской пейзаж, дождь, неон»
- Плохо: `city, night, rain, neon, cyberpunk, 4k`
- Хорошо: `masterpiece, best quality, cinematic night cityscape after rain, neon signs reflecting off wet asphalt, a lone figure crossing an empty crosswalk, blue hour atmosphere, volumetric fog, wide shot, anamorphic lens flare, cinematic color grading`

**4.** Задача: fantasy warrior portrait (частый фейл — переутяжеленные веса)
- Плохо: `((epic fantasy warrior)), ((extremely detailed armor:1.6)), ((perfect face:1.5)), masterpiece, 8k, trending`
- Хорошо: `masterpiece, best quality, photorealistic portrait of a fantasy warrior in dented steel plate armor, battle-worn cape, scar across left eyebrow, standing before a burning village, (dramatic rim lighting:1.2), dust particles in the air, cinematic composition, 8k uhd`

**5.** Задача (RU): «Двое друзей за столиком в кафе, один в синей куртке, вторая в красном платье» (мульти-персонажность)
- Плохо: `two friends, cafe, blue jacket, red dress, talking, cozy`
- Хорошо: `masterpiece, best quality, photorealistic photo of two friends at a cafe table, the man on the left wearing a navy blue jacket and laughing, the woman on the right wearing a red dress and holding a coffee cup, warm indoor lighting, shallow depth of field, natural candid photography`
