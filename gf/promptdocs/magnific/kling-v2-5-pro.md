---
target: magnific/kling-v2-5-pro
platform: magnific
syntax: natural
max_len: 400            # доки: prompt/negative_prompt каждый ≤2500 символов
negative: true
refs: single              # image — один driving-кадр для image-to-video
updated: 2026-07-06
sources: [docs.magnific.com/api-reference/image-to-video/kling-v2.5-pro/post-kling-v2-5-pro, fal.ai/learn/devs/kling-2-6-pro-prompt-guide]
---
# Как писать промпт для Magnific Kling 2.5 Pro (image-to-video)

Контекст: единственная видео-модель в этом рабочем наборе (Lion Films нужен хотя бы один видео-путь; `video_generate` у Hermes уже используется). Image-to-video: подаёшь стартовый кадр (`image` — обычно winner из курации) + текстовое описание движения (`prompt`) → получаешь короткий клип. Точный REST-путь не зафиксирован дословно в собранных доках (см. `sources` — страница описывает параметры, не показывает сырой URL построчно) — ориентируйся на название модели `kling-v2.5-pro` при выборе через MCP-инструмент `video_generate`, а не на угаданный путь.

## Структура промпта

`prompt` описывает **движение**, не статичную композицию (композиция уже задана стартовым кадром `image`) — доки прямо говорят: «prompt describes desired motion». Собирай из четырёх блоков (по практике площадки Kling в целом, не строгий протокол API, но рабочая эвристика):

1. **Сцена/свет** — коротко, только если начальный кадр не полностью это передаёт: `golden hour light, gentle breeze`.
2. **Что делает субъект** — конкретное действие с направлением/скоростью: `she slowly turns her head to look over her shoulder`, а не общее «она двигается».
3. **Камера** — если нужно движение камеры, а не статичный кадр: `camera slowly pushes in`, `camera pans left to reveal the skyline`, `static locked-off shot` (если камера должна стоять на месте — скажи это явно, а не полагайся на дефолт).
4. **Второстепенное движение** — деталь, которая делает клип живым: `hair and coat sway gently in the wind`, `steam rises from the cup`.

**Держи промпт согласованным со стартовым кадром** — если `image` показывает дневной интерьер, а `prompt` описывает совсем другую сцену/освещение, результат станет непредсказуемым (по практике площадки — рассинхрон источник/промпт даёт худшую связность движения, не смену сцены).

## Negative prompt

`negative_prompt` (до 2500 символов) — описывай **нежелательное движение/артефакты**, не общие неаппетитные слова из SDXL-негатива: `no camera shake, no extra people entering frame, no morphing face, no text overlays`. Это ближе к «что НЕ должно двигаться/произойти», чем к «плохое качество» — Kling это не CLIP-энкодер SDXL.

## Параметры

| Параметр | Тип/диапазон | Default | Комментарий |
|---|---|---|---|
| `duration` | `"5"` \| `"10"` (секунды) | — | обязателен; других значений нет |
| `image` | base64/URL, ≤10MB, мин. 300×300px, соотношение сторон 1:2.5…2.5:1 | — | стартовый кадр — подавай winner из курации |
| `prompt` | string, ≤2500 симв. | — | описание движения |
| `negative_prompt` | string, ≤2500 симв. | — | нежелательное движение/артефакты |
| `cfg_scale` | 0-1 | 0.5 | **не путать со шкалой 1-10/1-100 у образных моделей** — здесь 0-1: выше — точнее следует промпту, но менее «естественная»/гибкая физика движения; ниже — более живая, но может уйти от текста |
| `webhook_url` | URI | — | асинхронное уведомление |

## Особенности площадки

Кредиты: видео заметно дороже кадра — `simulate_cost` обязателен перед каждым запуском, особенно при `duration: "10"`. Локальный стартовый кадр (winner) не грузится напрямую как файл — флоу `creations_request_upload` → PUT → `creations_finalize_upload`; `creations_upload_image` принимает только http(s)-URL. Полное описание кредитов/upload-флоу/circuit-breaker — в `_catalog.md`.

## Типовые фейлы

- **Слишком сложный/противоречивый промпт движения** — несколько разнонаправленных движений камеры и субъекта одновременно («камера облетает по кругу, субъект бежит, время ускоряется») чаще даёт искажение движения («motion distortion»), чем связный клип; упрощай до одного главного движения камеры + одного главного действия субъекта.
- **Несогласованность промпта со стартовым кадром** — описание сцены, которой нет на `image`, не «переписывает» сцену, а ломает связность движения; меняй сцену через кадр (Mystic/Seedream), не через промпт видео.
- **`cfg_scale` близко к 1 при сложном движении** — слишком строгое следование тексту при сложной физике (ткань, волосы, несколько объектов) может дать неестественную, «дёрганую» анимацию; для сложных сцен пробуй средние значения (0.4-0.6), а не максимум.
- **Расчёт на явную камеру по умолчанию** — если камера должна стоять на месте, это надо сказать явно (`static locked-off shot`); без этого модель может добавить лёгкое движение камеры по своему усмотрению.
- **`negative_prompt` в стиле SDXL** (`low quality, blurry, watermark`) — здесь полезнее конкретные нежелательные движения/артефакты видео (`no face morphing, no flickering, no extra limbs appearing mid-motion`), а не общий список «качества».

## Примеры «задача → промпт»

**1.** Задача (RU): «Оживить winner-портрет: лёгкий поворот головы, ветер в волосах»
- `prompt`: `She slowly turns her head to look toward the camera, hair gently moving in a light breeze, soft golden-hour light. Static camera, no camera movement.`
- `negative_prompt`: `no face morphing, no extra people, no camera shake`
- Параметры: `image: <winner.png>`, `duration: "5"`, `cfg_scale: 0.5`.

**2.** Задача: короткий рекламный клип продукта — камера медленно наезжает
- `prompt`: `Camera slowly pushes in toward the perfume bottle, soft studio light glinting on the glass, steam-like light rays drifting subtly in the background.`
- `negative_prompt`: `no shaky camera, no objects appearing or disappearing, no text overlays`
- Параметры: `image: <product-still.png>`, `duration: "5"`, `cfg_scale: 0.6`.

**3.** Задача: пейзажный установочный план (кино-превиз), камера открывает панораму
- `prompt`: `Camera slowly pans right to reveal the full mountain valley, mist drifting gently across the peaks, birds flying in the distance.`
- `negative_prompt`: `no abrupt cuts, no distortion of the mountains, no flickering`
- Параметры: `image: <landscape-still.png>`, `duration: "10"`, `cfg_scale: 0.45`.

**4.** Задача (RU): «Персонаж делает шаг вперёд и смотрит в камеру, плащ развевается»
- `prompt`: `He takes a single step forward and looks directly into the camera, his coat swaying with the motion, dramatic side lighting. Camera remains static.`
- `negative_prompt`: `no morphing face, no extra limbs, no background objects moving erratically`
- Параметры: `image: <hero-still.png>`, `duration: "5"`, `cfg_scale: 0.55`.

**5.** Задача: интерьерная сцена кафе, пар от кофе, лёгкое покачивание камеры на плече
- `prompt`: `Steam rises gently from the coffee cup on the table, warm afternoon light through the window, subtle handheld camera sway.`
- `negative_prompt`: `no strong camera shake, no people appearing suddenly, no flickering light`
- Параметры: `image: <cafe-still.png>`, `duration: "5"`, `cfg_scale: 0.5`.
