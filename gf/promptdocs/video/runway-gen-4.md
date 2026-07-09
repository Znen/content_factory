---
target: video/runway-gen-4
platform: runway
syntax: natural
max_len: 500           # Runway прямо советует короткие, «succinct and focused» промпты; длинный промпт вредит
negative: false        # официальный Gen-4 Video guide не заявляет negative-параметр; нежелательное — перефразом
refs: single           # image-first: 1 стартовый кадр как визуальная основа клипа
updated: 2026-07-09
sources: [help.runwayml.com/hc/en-us/articles/39789879462419-Gen-4-Video-Prompting-Guide, filmart.ai/runway-gen-4-prompts]
---
# Как писать промпт для Runway Gen-4 (image-first: i2v + t2v)

Контекст: видео-модель Runway. **Image-first** — входной кадр это визуальная основа всего клипа (задаёт субъект, композицию, цвет, свет, стиль), поэтому основной режим — **image-to-video**, а промпт описывает **движение**, а не картинку. Клипы 5 или 10 секунд. Философия Runway — **простота**: начинай с короткого промпта и добавляй детали итерациями; «visual detail over conversation» — никаких приветствий и объяснений, только визуальные указания. Одно движение на предложение. Путь исполнения завод пока не выбрал — паспорт работает в явном режиме (`gf_write_prompt`).

## Image-to-video (i2v) — основной режим

Стартовый кадр уже задал композицию — промпт описывает **движение** по четырём блокам (рекомендация официального гайда):

1. **Subject Motion** — что делает субъект: активные глаголы `run`, `glide`, `turn`, `lean`, `jump`. Ссылайся на субъект обобщённо — `the subject`, `she`, `he`, не переописывай его внешность (она на кадре).
2. **Scene Motion** — как реагирует/меняется окружение: `dust rises with each step`, `petals drift softly`, `birds scatter`.
3. **Camera Motion** — движение/ракурс камеры (словарь ниже).
4. **Style Descriptor** — визуальное настроение/эстетика, коротко.

Логический порядок: **субъект → действие → камера/стиль**. Держи промпт «succinct and focused» — Gen-4 лучше работает на коротком точном промпте, чем на простыне.

**Словарь движения камеры (рекомендованный Runway):** `tracking` (следует за субъектом), `panning` (горизонтальный поворот), `tilting` (вертикальный), `dolly` (вперёд/назад), `handheld` (лёгкая живая тряска), `static` / `locked` (камера стоит — говори явно, если движения быть не должно).

## Text-to-video (t2v) — вторичный режим

Runway Gen-4 — image-first, и гайд заточен под i2v; для лучшего контроля **сначала сгенерируй стартовый кадр** (Mystic/Seedream/SDXL из завода) и иди через i2v. Если всё же t2v: промпт описывает и композицию сцены, и движение — но помни, что без входного кадра модель слабее держит консистентность, чем в i2v. Структура та же (субъект → действие → камера → стиль), плюс краткое описание самой сцены/локации в начале.

## Negative prompt

Официальный Gen-4 Video guide **не заявляет** negative-параметр. Нежелательное убирай **позитивным перефразом**: не «no camera shake», а `static locked camera`; не «no extra people», а `the alley is empty`. Список запретов в промпт не добавляй — это шум и упоминание нежелательного.

## Параметры

| Параметр | Значения | Комментарий |
|---|---|---|
| режим | image-to-video (осн.) / text-to-video | i2v предпочтителен — входной кадр держит консистентность |
| duration | `5` \| `10` секунд | другие длительности гайдом не заявлены |
| input image | стартовый кадр | визуальная основа — качество кадра напрямую определяет качество клипа |
| промпт | короткий, 4 блока движения | «succinct and focused»; длинный промпт вредит |

**Эвристика:** точные API-параметры (разрешение, aspect, seed) зависят от площадки/версии (Gen-4, Gen-4 Turbo); гайд фокусируется на **тексте промпта**, а не на параметрах. Разрешение/соотношение обычно наследуются из входного кадра — сверять по конкретному провайдеру. Структуру промпта и словарь камеры — по официальному Runway-гайду (см. `sources`).

## Особенности

- **Качество стартового кадра решает всё** — Gen-4 строит клип поверх входного изображения; слабый/шумный кадр = слабый клип. Подавай winner из курации, не черновик.
- **Короткий промпт — фича, не баг.** Runway явно советует начинать просто и итерировать; в отличие от Veo (где длинный timestamp-промпт нормален), Gen-4 не любит перегруз.
- **Одна сцена на клип.** Попытка расписать несколько смен сцен/действий/стилей в 5–10 с даёт непредсказуемый результат — разбивай на последовательные клипы.
- Путь исполнения заводом не выбран; при доступе через API имена параметров сверять с площадкой.

## Типовые фейлы

- **Переописание того, что уже на кадре** — `beautiful woman with brown hair in a red dress standing in a field` вместо описания движения: тратит короткий промпт, композиция уже задана кадром. Пиши только движение.
- **Несколько конфликтующих действий сразу** — «камера облетает, субъект бежит, стиль меняется, время ускоряется»: Runway явно предупреждает против перегруза; одно движение на предложение, одно главное — на клип.
- **Разговорный/LLM-стиль промпта** — `Please create a beautiful cinematic video where...`: «visual detail over conversation», приветствия и объяснения тратят место. Только визуальные указания.
- **Негатив-список** (`no blur, no artifacts, low quality`) — у Gen-4 нет негатива; шумит промпт. Перефразируй позитивно.
- **Расчёт на неявную камеру** — если камера должна стоять, скажи `static` / `locked`; иначе Runway добавит движение сам.
- **Длинный «богатый» промпт** — Gen-4 деградирует на простынях; держи коротко и точно, добавляй детали итерациями, а не всё сразу.
- **t2v там, где нужен контроль** — для консистентного результата сгенерируй стартовый кадр и иди через i2v, а не проси Gen-4 нарисовать всё с нуля текстом.

## Примеры «задача → плохо → хорошо»

**1. (i2v)** Задача (RU): «Оживить winner-портрет: субъект поворачивается к камере, ветер, камера стоит»
- Плохо: `a beautiful young woman with long brown hair wearing a blue coat, golden hour, highly detailed, 8k, she turns` — переописывает то, что уже на кадре, длинно, «she turns» без блоков движения/камеры.
- Хорошо: `The subject slowly turns to face the camera. Her hair drifts in a light breeze. Static locked camera. Soft golden-hour mood.`
- Параметры: `input image: <winner.png>`, `duration: 5`.

**2. (i2v, экшн)** Задача: героя гонят по переулку, камера следует сзади
- Плохо: `the character runs and jumps and dodges while the camera spins around him and zooms and the lighting flickers dramatically` — свалка конфликтующих движений камеры и субъекта → непредсказуемый результат.
- Хорошо: `The subject sprints down the narrow alley, dodging crates and leaping over a low wall. Dust kicks up behind him. The camera tracks from behind. Tense, high-contrast mood.`
- Параметры: `input image: <alley-still.png>`, `duration: 10`.

**3. (i2v, драма)** Задача: пара под цветущим деревом, лепестки, камера открывает закат
- Плохо: `romantic scene, beautiful couple, cherry blossoms everywhere, amazing cinematic masterpiece, emotional` — теги-вайбы без единого конкретного движения; модель не знает, что двигать.
- Хорошо: `The couple embraces beneath the blooming cherry tree. Petals drift softly around them. The camera slowly tilts up to reveal the sunset glow. Warm, tender mood.`
- Параметры: `input image: <couple-still.png>`, `duration: 10`.

**4. (i2v, документалка/природа)** Задача: панорама по саванне со стадом слонов
- Плохо: `elephants in savanna, nature documentary, 4k, David Attenborough style, no blur, no artifacts` — SDXL-негатив (у Gen-4 нет), «style» отсылкой к персоне, нет структуры движения.
- Хорошо: `The camera pans slowly across the vast savanna as a herd of elephants moves gracefully. Dust rises with each step and birds scatter as they pass. Warm dusk light.`
- Параметры: `input image: <savanna-still.png>`, `duration: 10`.

**5. (t2v, вторичный режим)** Задача: короткий установочный план — маяк в шторм (нет готового кадра)
- Плохо: `make a video of a lighthouse in a storm, very dramatic and cinematic, lots happening` — «lots happening» = перегруз, разговорный стиль, t2v без якорного кадра теряет консистентность.
- Хорошо (лучше — через i2v: сгенерировать кадр маяка в Mystic/SDXL, затем анимировать; если t2v): `A lone lighthouse on a rocky cliff during a storm, waves crashing below, its beam sweeping through the rain. The camera slowly pushes in. Dark, moody, high-contrast.`
- Параметры: `duration: 5` (рекомендация: сгенерировать стартовый кадр и перейти в i2v).
