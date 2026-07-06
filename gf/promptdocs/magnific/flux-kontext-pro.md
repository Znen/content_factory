---
target: magnific/flux-kontext-pro
platform: magnific
syntax: natural           # инструкция-редактирование, не тег-суп
max_len: 200
negative: false
refs: single              # input_image — один референс/исходное изображение
updated: 2026-07-06
sources: [docs.magnific.com/api-reference/text-to-image/flux-kontext-pro/overview, replicate.com/blog/flux-kontext, magnific.com/ai/docs/image-ai-models]
---
# Как писать промпт для Magnific Flux Kontext Pro

Контекст: Flux Kontext Pro (Black Forest Labs, хостится на площадке Magnific) — модель **instruction-based editing**: даёшь исходное изображение (`input_image`, один референс) и текстовую **инструкцию**, что именно изменить, а не полное текстовое описание всей сцены заново. По каталог-странице площадки — «style and object consistency across prompts», годится под задачи Lion Films типа «поправить уже выбранный финальный кадр, не переделывая его с нуля» (смена фона/одежды/освещения при сохранении композиции и идентичности). Для сшивки **нескольких** референсов (лицо+локация) эта модель не подходит — только один `input_image`; для этого бери `seedream-v4-5-edit`. Как и в остальных magnific-паспортах: имена полей в MCP-обёртке Hermes (`images_generate`) могут не совпадать с сырыми REST-полями ниже — при ошибке валидации доверяй фактическому ответу инструмента.

## Структура промпта

Промпт — **инструкция**, а не описание сцены целиком: `{глагол-действие} {что именно меняем} {на что} {что сохранить неизменным}`.

1. **Глагол выбирай осознанно** — `transform` провоцирует полную переработку/потерю идентичности; `change`, `replace`, `add`, `remove` — точечное, управляемое изменение одного аспекта.
2. **Называй субъект прямо**, не местоимением: `the woman in the blue dress`, а не «she» — местоимение хуже держит, какой объект редактируем при сложной сцене.
3. **Явно проговаривай, что остаётся неизменным** — иначе модель может сдвинуть то, что менять не просили: `change the background to a beach while keeping the person in the exact same position, camera angle, and framing`.
4. **Для текста в кадре** — формат кавычек: `replace "OLD TEXT" with "NEW TEXT"`; держись читаемых шрифтов и старайся сохранить длину текста похожей, иначе может поехать вёрстка.
5. **Для смены стиля** — называй конкретный художественный стиль (`impressionist painting`, `1960s pop art`), а не общее «сделай художественно»; если название стиля не срабатывает — перечисли его признаки словами (`visible brushstrokes, thick paint texture, rich color depth`).
6. **Начинай с простого и итерируй** — модель поддерживает последовательное редактирование; сложную правку разбивай на 2-3 маленьких шага (вызов за вызовом), а не одну переусложнённую инструкцию.

## Параметры

| Параметр | Диапазон | Default | Комментарий |
|---|---|---|---|
| `prompt` | string | — | инструкция редактирования |
| `input_image` | URL | — | опционально; без него — обычная t2i-генерация с нуля (не редактирование) |
| `aspect_ratio` | `square_1_1, classic_4_3, traditional_3_4, widescreen_16_9, social_story_9_16, standard_3_2` | `square_1_1` | шесть вариантов — меньше, чем у Mystic/Seedream |
| `guidance_scale` | 1-10 | 3.0 | выше — точнее следует инструкции промпта, но меньше «естественности» правки |
| steps (inference steps) | 1-100 | — | выше — качественнее и дольше |
| `seed` | int | — | тот же seed + тот же промпт/настройки → воспроизводимый результат |
| prompt upsampling (авто-расширение промпта) | bool | — | включай для более творческого/детализированного результата; выключай, если нужна предсказуемая точечная правка |

Негативного промпта в этой модели нет — нежелательное всегда переформулируется позитивно (как в Nano), а не через отдельное поле.

## Особенности площадки

Кредиты: `simulate_cost` перед батчем итеративных правок — несколько последовательных вызовов на одном кадре суммируются в цене, посчитай заранее, а не после. Локальный `input_image` не грузится напрямую — `creations_request_upload` → PUT → `creations_finalize_upload`; `creations_upload_image` — только для http(s)-URL. Подробности (upload-флоу, circuit-breaker) — в `_catalog.md`.

## Типовые фейлы

- **`transform` вместо точечного глагола** — «transform the person into a Viking» рискует полностью заменить личность/лицо персонажа вместо точечной правки одежды/фона; если нужно сохранить идентичность — редактируй конкретные атрибуты (`change her clothing to`, `replace the background with`), не «трансформируй».
- **Местоимение вместо явного субъекта** в сцене с 2+ объектами — модель может отредактировать не того, если сказано просто «her»/«it» без уточнения, кто это.
- **Не проговорено, что сохранить** — без явного `keeping the same position/angle/framing` модель может незаметно сдвинуть композицию заодно с запрошенной правкой.
- **Сложная многошаговая правка одним промптом** — «поменяй фон, одежду и время суток одновременно» одним вызовом даёт менее предсказуемый результат, чем три последовательных точечных вызова.
- **Стилизованный/декоративный шрифт в тексте-правке** — по гайду BFL плохо рендерится; держись читаемых шрифтов и указывай их словами (`bold sans-serif`), не именем конкретного шрифта.

## Примеры «задача → плохо → хорошо»

**1.** Задача (RU): «На готовом кадре поменять фон на пляж, человека не трогать»
- Плохо: `beach background, sunny, turquoise water, person, high quality, no changes to face` — тег-суп вместо инструкции: нет глагола-действия, не сказано, что сохранить (позу/кадрирование), «no changes» — негатив-формулировка вместо явного «keeping...».
- Хорошо: `Change the background to a sunny beach with turquoise water, while keeping the person in the exact same position, pose, and camera framing. Do not alter the person's face, clothing, or expression.`
- Параметры: `input_image: <winner-кадр>`, `guidance_scale: 4`.

**2.** Задача: сменить куртку персонажа на кожаную чёрную, не трогая остальное
- Плохо: `Transform him into a man in a black leather jacket` — глагол `transform` + местоимение «him»: рискует переработать персонажа целиком (потеря лица/идентичности) и неясно, кого редактировать, если в кадре двое.
- Хорошо: `Replace the man's jacket with a fitted black leather jacket, keeping his face, pose, and the background exactly unchanged.`
- Параметры: `input_image: <источник>`, `guidance_scale: 5`.

**3.** Задача: правка текста на вывеске в кадре
- Плохо: `Change the sign to say ЗАКРЫТО in Helvetica Neue, make it look nice` — текст без кавычек и без формата `replace "X" with "Y"`, техническое имя шрифта вместо словесного описания, «make it look nice» — пустая инструкция.
- Хорошо: `Replace the sign text "OPEN" with "ЗАКРЫТО", keeping the same bold sans-serif font style and approximate text length.`
- Параметры: `input_image: <источник с вывеской>`.

**4.** Задача (RU): «Перевести фото в стиль импрессионистской живописи, не меняя композицию»
- Плохо: `Make it artistic and painterly, more beautiful` — «сделай художественно» без имени конкретного стиля или его признаков даёт случайную стилизацию; композиция не защищена явным «keeping...».
- Хорошо: `Convert the image into an impressionist painting style with visible brushstrokes, thick paint texture, and rich warm color depth, while keeping the exact same composition and subject placement.`
- Параметры: `input_image: <источник>`, `guidance_scale: 3` (ниже — чтобы не задавить стиль слишком буквальным следованием инструкции).

**5.** Задача: поменять фон И добавить реквизит (сложная правка)
- Плохо: одним вызовом — `Change the background to a foggy forest at dawn, add a lit lantern in the person's right hand, and adjust the lighting to match` — три изменения в одной инструкции дают менее предсказуемый результат и труднее локализовать, что именно пошло не так.
- Хорошо (два последовательных вызова): шаг 1 — `Change the background to a foggy forest at dawn, keeping the person's position, pose, and framing exactly unchanged.`; шаг 2 (на результате шага 1) — `Add a lit lantern in the person's right hand, keeping everything else in the image unchanged.`
- Параметры: `input_image` шага 2 — результат шага 1, не исходный кадр; `guidance_scale: 4` на обоих шагах.

## Когда НЕ брать эту модель

- Нужно **сшить два разных источника** (лицо с одного фото + локация с другого) — здесь только один `input_image`; для этого бери `seedream-v4-5-edit`.
- Нужна генерация **с нуля без исходного кадра** в кино-стилистике — `mystic` даёт больше стилевых рычагов (LoRA-персонажи, палитра, движок резкости).
- Нужно **оживить** уже готовый кадр — это t2i/edit-модель, для видео смотри `kling-v2-5-pro`.
