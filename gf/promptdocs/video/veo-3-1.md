---
target: video/veo-3-1
platform: veo
syntax: natural
max_len: 1500          # жёсткого лимита доки не дают; промпт может быть длинным (timestamp-мультишот), но связность важнее объёма
negative: true         # у Veo есть negativePrompt-параметр; описывать через позитивное отсутствие (см. ниже)
refs: multi            # i2v: 1 стартовый кадр; first+last frame: 2; ingredients-to-video: несколько референс-картинок (персонаж/локация/объект)
updated: 2026-07-09
sources: [cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1, deepmind.google/models/veo/prompt-guide]
---
# Как писать промпт для Google Veo 3.1 (t2v + i2v + native audio)

Контекст: флагманская видео-модель Google DeepMind. Уникальна **нативным синхронным звуком** — диалоги, SFX и музыка генерируются вместе с картинкой из того же промпта (главная причина брать Veo, а не Kling/Seedance/Runway, где звук отдельно). Клипы 4/6/8 секунд, 720p или 1080p, 16:9 или 9:16. Умеет: text-to-video, image-to-video (анимация стартового кадра), first+last frame (переход между двумя кадрами), ingredients-to-video (несколько референс-картинок для консистентности персонажа/локации/объекта). Все ролики несут вотермарк SynthID. Путь исполнения завод пока не выбрал — паспорт работает в явном режиме (`gf_write_prompt`), Hermes исполняет промпт своим путём.

## Text-to-video (t2v)

Модель рисует сцену, движение и звук с нуля — промпт описывает **всё**. Официальная формула из пяти блоков, **в этом порядке**:

**`[Cinematography] + [Subject] + [Action] + [Context] + [Style & Ambiance]`**

1. **Cinematography** (первым — самый сильный рычаг тона): тип плана и движение камеры — `Medium shot`, `Crane shot starting low and ascending`, `Close-up with shallow depth of field`, `Tracking shot following...`.
2. **Subject**: главный субъект конкретно — `a tired corporate worker`, `a lone hiker`.
3. **Action**: что делает, с направлением — `rubbing his temples in exhaustion`, `pushing aside a jungle vine to reveal a hidden path`.
4. **Context**: окружение и фон — `in a cluttered 1980s office late at night`.
5. **Style & Ambiance**: эстетика, настроение, свет — `retro aesthetic, shot as if on 1980s color film, slightly grainy`.

Отличие от image-промпта: здесь есть **время и движение**. Каждый блок описывает не статичный кадр, а развитие за 4-8 секунд — камера едет, субъект действует, свет живёт. Одно главное движение камеры + одно главное действие субъекта на клип; не пытайся уложить сцен на 30 секунд в 8-секундный ролик (для этого timestamp-мультишот, см. ниже).

## Image-to-video (i2v)

Композиция уже задана стартовым кадром — промпт описывает **только движение и камеру**, как в Kling. Не переописывай, что уже видно на кадре (субъект, цвета, композиция) — это тратит промпт и может рассинхронить результат. Держи движение **согласованным со стартовым кадром**: если кадр — дневной интерьер, не проси ночную улицу (сцена не «перепишется», сломается связность).

- **Один стартовый кадр:** `The camera slowly pushes in as she turns her head toward the window, soft curtains drifting in a light breeze.`
- **First + last frame** (переход между двумя кадрами): промпт описывает саму **траекторию перехода** — `The camera performs a smooth 180-degree arc, starting front-facing and circling to end on a POV shot from behind.`
- **Ingredients-to-video** (несколько референсов для консистентности): ссылайся на приложенные картинки по роли — `Using the provided images for the detective, the woman, and the office, create a medium shot of the detective behind his desk...`.

## Аудио (фишка Veo)

Звук генерируется нативно из того же промпта. Три типа звуковых указаний — **пиши их явными пометками**, не растворяй в описании сцены:

- **Диалог — в кавычках, с атрибуцией говорящего:** `A woman says, "We have to leave now."` или `The detective replies in a weary voice, "Of all the offices in this town, you had to walk into mine."`. Реплика попадёт в липсинк; тон задаётся словами до кавычек (`in a weary voice`, `whispering`, `shouting`).
- **Sound effects — префикс `SFX:`** — `SFX: thunder cracks in the distance`, `SFX: the rustle of dense leaves, distant exotic bird calls`.
- **Ambient / музыка — `Ambient noise:` или описание партитуры** — `Ambient noise: the quiet hum of a starship bridge`, `SFX: a swelling, gentle orchestral score begins to play`.

Правило: описывай звук **конкретно**, как картинку. Не `music`, а `a slow melancholic piano melody`. Не `he talks`, а точная реплика в кавычках. Учитывай длину клипа — в 8 секунд не влезет длинный монолог; держи реплику короткой (1-2 фразы).

**Timestamp-мультишот** (несколько кадров в одном ролике с точным таймингом) — блоки `[MM:SS-MM:SS]`, каждый со своей камерой, действием и звуком:
```
[00:00-00:02] Medium shot from behind a young explorer as she pushes aside a jungle vine to reveal a hidden path.
[00:02-00:04] Reverse shot of her freckled face, filled with awe. SFX: distant exotic bird calls. Emotion: wonder.
[00:04-00:08] Wide high-angle crane shot revealing her small in a vast forgotten temple. SFX: a swelling orchestral score begins.
```

## Negative prompt

У Veo есть параметр negative, но **золотое правило — позитивное отсочётание, а не список запретов**. Описывай желаемое **отсутствие как состояние сцены**, а не через «no»:
- Хорошо: `a desolate landscape with no buildings or roads` (конкретное пустое состояние).
- Плохо: `no man-made structures, no people, no cars` — упоминание объекта в промпте **повышает** вероятность его появления (та же ловушка, что у Gemini/Nano).
Для видео полезно исключать нежелательные **артефакты движения**: `no camera shake` (если камера должна стоять), `no morphing`, `no extra limbs`.

## Параметры

| Параметр | Значения | Комментарий |
|---|---|---|
| duration | `4` \| `6` \| `8` секунд | других длительностей нет; звук и действие планируй под выбранную |
| resolution | `720p` \| `1080p` | 1080p дороже; часть площадок заявляет и 4K — сверять по конкретному провайдеру |
| aspect_ratio | `16:9` \| `9:16` | горизонталь / вертикаль |
| negativePrompt | string | позитивное отсочётание (см. выше) |
| audio | нативно из промпта | отдельного флага «включить звук» в промпте нет — звук задаётся текстом (`"..."`, `SFX:`, `Ambient noise:`) |

**Эвристика:** точный набор параметров и лимитов зависит от провайдера доступа (Google AI Studio / Vertex AI / сторонний API) — перед продовым запуском сверять с конкретной площадкой. Длительности/разрешения/формулу промпта — по официальному Google-гайду (см. `sources`).

## Особенности

- **Звук — главная причина брать Veo.** Если задача без диалога/атмосферы — Kling/Seedance/Runway могут быть дешевле; Veo оправдан там, где нужен синхронный звук в один проход.
- **SynthID watermark** на всех роликах — не для незаметной подмены реального видео.
- **Add/Remove Object** на части площадок работает на старом Veo 2 и **без звука** — не путать с генерацией.
- Путь исполнения заводом не выбран; если пойдёт через Magnific/сторонний API — сверять имена параметров с площадкой.

## Типовые фейлы

- **Звук растворён в описании сцены** — `they have a conversation about leaving` вместо реплики в кавычках: модель не знает, что именно сказать, липсинк выйдет мычанием. Диалог — всегда `"в кавычках"` с атрибуцией.
- **Список запретов в negative** (`no cars, no people`) — упоминание объекта повышает его вероятность; описывай пустое состояние позитивно (`an empty street at dawn`).
- **Перегруз 8-секундного клипа** — три смены локации и монолог на минуту в один 8с-ролик: получится каша. Либо упрощай до одного действия, либо разбивай timestamp-блоками с реалистичным таймингом.
- **i2v переописывает стартовый кадр** — повтор композиции/цветов, которые уже на кадре, вместо описания движения: тратит промпт и рассинхронит. На i2v пиши только движение + камеру.
- **Рассинхрон промпта и стартового кадра** (i2v) — просить ночную улицу поверх дневного интерьерного кадра: сцена не сменится, сломается связность движения. Сцену меняют кадром, не видео-промптом.
- **Камера по умолчанию** — если камера должна стоять, скажи явно (`static locked-off shot`); иначе Veo может добавить движение по своему усмотрению.
- **Длинный диалог в короткий клип** — реплика не влезет в 4-6 секунд и обрежется; держи 1-2 короткие фразы под длину.

## Примеры «задача → плохо → хорошо»

**1. (t2v + audio)** Задача (RU): «Ночной город, девушка идёт под неоном, роняет реплику в камеру»
- Плохо: `girl walking in neon city at night, cinematic, 4k, beautiful, she says something about the rain` — статичный image-стиль (нет камеры/движения), реплика не в кавычках (модель не знает текст → липсинк-мычание), «cinematic/4k» вместо конкретики.
- Хорошо:
  - `Tracking shot following a young woman from behind as she walks slowly down a rain-slicked neon-lit street at night, glancing over her shoulder toward the camera. She says in a quiet voice, "You shouldn't have followed me here." Reflections of pink and blue neon shimmer on the wet asphalt. Ambient noise: distant city traffic and light rain. Moody cyberpunk aesthetic, shallow depth of field.`
- Параметры: `duration: 8`, `resolution: 1080p`, `aspect_ratio: 16:9`.

**2. (t2v, чистая атмосфера/звук)** Задача: установочный план грозы над океаном для превиза
- Плохо: `storm over the ocean, dramatic, epic, loud thunder sounds and rain and wind and music all together` — свалка звуков без структуры (модель не разберёт приоритет), нет камеры и плана.
- Хорошо:
  - `Wide aerial crane shot descending toward a stormy ocean at dusk, massive dark waves rolling under heavy clouds. SFX: thunder cracks in the distance, wind howling. Ambient noise: the deep roar of the sea. Cinematic, desaturated cold color grade, high contrast.`
- Параметры: `duration: 6`, `resolution: 1080p`, `aspect_ratio: 16:9`, `negativePrompt: a clear calm sky with no boats`.

**3. (i2v)** Задача (RU): «Оживить winner-портрет: лёгкий поворот головы, ветер, без движения камеры»
- Плохо: `beautiful woman portrait, golden hour, 8k, masterpiece, she turns and the camera zooms and pans around her` — переописывает то, что уже на кадре, и три движения камеры сразу → motion distortion; композиция уже задана стартовым кадром.
- Хорошо:
  - `She slowly turns her head to look toward the camera, a few strands of hair drifting in a light breeze. Static locked-off camera, no camera movement. Soft golden-hour light.`
- Параметры: `image: <winner.png>`, `duration: 4`, `resolution: 1080p`, `negativePrompt: no face morphing, no extra people`.

**4. (i2v + dialogue, ingredients)** Задача: диалоговая сцена детектива с консистентными персонажами
- Плохо: `detective and woman talking in office, noir style, they discuss the case for a while` — нет конкретной реплики (звук провалится), нет камеры, «for a while» не влезет в клип.
- Хорошо:
  - `Using the provided images for the detective, the woman, and the office setting, medium shot of the detective behind his desk. He looks up at the woman and says in a weary voice, "Of all the offices in this town, you had to walk into mine." Ambient noise: rain against the window, a ticking clock. Film-noir lighting, hard shadows.`
- Параметры: `refs: [detective.png, woman.png, office.png]`, `duration: 8`, `aspect_ratio: 16:9`.

**5. (first+last frame)** Задача: плавный переход-облёт между двумя готовыми кадрами (превиз концерта)
- Плохо: `singer on stage, concert, transition between the two images somehow, cool camera move` — «somehow/cool» не задаёт траекторию; модель не поймёт, как соединить кадры.
- Хорошо:
  - `The camera performs a smooth 180-degree arc, starting on the front-facing view of the singer and circling around her to seamlessly end on the POV shot from behind her, facing the crowd. Stage lights sweep across the arena. SFX: a roaring crowd, a driving drumbeat.`
- Параметры: `first: <front.png>`, `last: <behind.png>`, `duration: 6`, `aspect_ratio: 16:9`.
