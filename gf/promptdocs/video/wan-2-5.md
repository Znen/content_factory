---
target: video/wan-2-5
platform: wan
syntax: natural
max_len: 800           # доки не дают жёсткого лимита; есть prompt_extend (авто-расширение), так что короткий связный промпт ок
negative: true         # у Wan есть параметр negative_prompt
refs: single           # i2v: 1 стартовый кадр; аудио задаётся отдельным audio-URL (не визуальный референс)
updated: 2026-07-09
sources: [alibabacloud.com/help/en/model-studio/use-video-generation, atlascloud.ai/models/alibaba/wan-2.5/image-to-video, wavespeed.ai/models/alibaba/wan-2.5/image-to-video]
---
# Как писать промпт для Alibaba Wan 2.5 (t2v + i2v)

Контекст: видео-модель Alibaba (Tongyi Wanxiang / 通义万相), опенсорс-семейство Wan. Две превью-модели: `wan2.5-t2v-preview` (текст→видео) и `wan2.5-i2v-preview` (кадр→видео). Как и Veo, умеет **нативный синхронный звук** (голос, SFX, липсинк) в один проход; опционально можно подать `audio`-URL как гайд. Клипы 5 или 10 секунд, 480p/720p/1080p, 16:9/9:16/1:1, вывод 30 fps H.264. Есть настоящий `negative_prompt` и `prompt_extend` (авто-обогащение промпта). Путь исполнения завод пока не выбрал — паспорт работает в явном режиме (`gf_write_prompt`).

## Text-to-video (t2v)

`wan2.5-t2v-preview` рисует сцену и движение с нуля — промпт описывает всё: **субъект → действие с направлением → окружение → движение камеры → темп → свет/стиль**. Как у любой кино-t2v модели, держи одно главное движение камеры + одно действие субъекта на клип (5 или 10 с). Wan хорошо тянет фотореалистичное движение и синхронный звук, если он задан в промпте.

Опция `prompt_extend` (расширение промпта) — модель сама дообогащает короткий промпт кинематографичными деталями. Полезно для черновиков; для точного контроля лучше писать детальный промпт вручную и не полагаться на авто-расширение (оно может увести стиль).

## Image-to-video (i2v)

`wan2.5-i2v-preview` — композиция задана стартовым кадром, промпт описывает **только движение и камеру**. Не переописывай, что уже на кадре; держи движение согласованным со стартовым кадром (свет/время суток не «переписываются» промптом). Отдельная сила Wan-i2v — **консистентность освещения** при анимации и синхронный звук, если он нужен.

`prompt`: `The camera slowly pushes in as she raises her eyes to the camera, soft window light, a gentle breeze moving her hair.`

## Аудио

Wan генерирует звук нативно и синхронно (в отличие от Kling/Runway, где звук отдельно). Два пути:
- **Из промпта:** опиши звук конкретно, как у Veo — реплики, атмосферу, музыку (`a soft piano melody`, `distant city traffic`, короткая реплика в кавычках для липсинка).
- **Через `audio`-URL:** подать готовую дорожку как гайд (модель подстроит движение/липсинк под неё) — полезно, когда музыка/голос уже готовы.
Как и везде: не `music`, а конкретное описание; реплику держи короткой под 5–10 с.

## Negative prompt

У Wan есть `negative_prompt` — но для видео полезнее описывать **нежелательное движение/артефакты**, а не SDXL-список качества. `no camera shake` (если камера должна стоять), `no face morphing, no flickering, no extra limbs appearing`. Общий `low quality, blurry, watermark` малополезен — Wan не CLIP-энкодер SDXL.

## Параметры

| Параметр | Значения | Комментарий |
|---|---|---|
| model | `wan2.5-t2v-preview` \| `wan2.5-i2v-preview` | t2v / i2v |
| duration | `5` \| `10` секунд | других нет |
| resolution | `480P` \| `720P` \| `1080P` | 1080p дороже/медленнее |
| aspect_ratio | `16:9` \| `9:16` \| `1:1` | i2v обычно наследует из кадра — сверять по площадке |
| fps / формат | 30 fps, MP4 (H.264) | фиксировано |
| negative_prompt | string | нежелательное движение/артефакты (см. выше) |
| prompt_extend | bool | авто-расширение промпта; для точного контроля выключать |
| audio | URL (опц.) | готовая дорожка как гайд синхронизации |

**Эвристика:** точные имена полей и лимиты зависят от площадки доступа (Alibaba Model Studio / сторонний API — Atlas/WaveSpeed/Kie). Перед продовым запуском сверять с конкретным провайдером; длительности/разрешения/аудио/негатив — по докам Alibaba и провайдеров (см. `sources`).

## Особенности

- **Нативный звук + опциональный audio-URL** — как у Veo, отличает Wan от Kling/Seedance/Runway. Если задача со звуком — Wan/Veo, а не остальные.
- **`prompt_extend`** удобен для быстрых черновиков, но уводит стиль — для финала пиши детальный промпт сам и выключай расширение.
- **Опенсорс-семейство** — Wan быстро версионируется (2.5/2.6/2.7…); имена моделей и лимиты сверять с текущей докой провайдера, не полагаться на память.
- Путь исполнения заводом не выбран; при доступе через сторонний API — имена параметров могут отличаться от Alibaba Model Studio.

## Типовые фейлы

- **SDXL-негатив в `negative_prompt`** (`low quality, blurry, watermark`) — для видео полезнее конкретные нежелательные движения/артефакты (`no face morphing, no flickering, no extra people entering frame`).
- **i2v переописывает стартовый кадр** — повтор композиции/цветов вместо описания движения: тратит промпт, рассинхронит. На i2v пиши только движение + камеру.
- **Рассинхрон промпта и кадра** (i2v) — другой свет/время суток, чем на кадре: не «перепишется», сломает связность. Сцену меняют кадром.
- **Ставка на `prompt_extend` для финала** — авто-расширение добавит своих деталей и уведёт стиль; на финале контролируй промпт вручную.
- **`music`/`he talks` вместо конкретики** — звук провалится или выйдет обобщённым; описывай дорожку и реплики конкретно, короткой под длину клипа.
- **Ожидание сцен на 30 секунд в 5–10 с клипе** — Wan короткий; одно движение + одно действие, не раскадровка целой сцены.

## Примеры «задача → плохо → хорошо»

**1. (t2v + audio)** Задача (RU): «Уличный музыкант играет на скрипке в дождь, слышно скрипку и дождь»
- Плохо: `street musician playing violin in the rain, cinematic, 4k, beautiful, music playing` — статичный image-стиль (нет движения/камеры), `music playing` вместо конкретного звука, «4k/beautiful» вместо деталей.
- Хорошо:
  - `prompt`: `Medium shot of a street musician playing a slow, melancholic violin melody under a light rain, the camera gently pushing in as raindrops fall through the warm streetlight. Ambient sound of soft rain and distant traffic.`
  - `negative_prompt`: `no camera shake, no people walking into frame`
- Параметры: `model: wan2.5-t2v-preview`, `duration: 10`, `resolution: 1080P`, `aspect_ratio: 16:9`, `prompt_extend: false`.

**2. (i2v)** Задача: оживить winner-портрет — взгляд в камеру, ветер, статичная камера
- Плохо: `beautiful woman, golden hour, 8k, masterpiece, she moves` + `negative_prompt: low quality, blurry, watermark` — переописывает кадр, «she moves» без направления, SDXL-негатив вместо нежелательных движений.
- Хорошо:
  - `prompt`: `She slowly raises her eyes to look into the camera, a few strands of hair drifting in a light breeze, soft golden-hour light. Static camera.`
  - `negative_prompt`: `no face morphing, no camera shake, no extra people`
- Параметры: `model: wan2.5-i2v-preview`, `duration: 5`, `resolution: 1080P`.

**3. (t2v, продукт)** Задача: рекламный клип флакона — медленный наезд, блик на стекле
- Плохо: `perfume bottle, camera orbits around it 360 while zooming, lights flashing, fast dynamic` — несколько разнонаправленных движений камеры сразу → motion distortion; для продукта нужно одно простое движение.
- Хорошо:
  - `prompt`: `The camera slowly pushes in toward a perfume bottle on a reflective surface, soft studio light glinting across the glass, faint light rays drifting in the background.`
  - `negative_prompt`: `no shaky camera, no objects appearing or disappearing, no text overlays`
- Параметры: `model: wan2.5-t2v-preview`, `duration: 5`, `resolution: 1080P`, `aspect_ratio: 1:1`.

**4. (i2v + готовая музыка)** Задача: анимировать кадр танцовщицы под уже готовый трек
- Плохо: `dancer moving to the music, energetic, cool` — «cool/energetic» не задаёт движение, музыка не привязана.
- Хорошо:
  - `prompt`: `She sways and turns gracefully in time with the music, fabric flowing around her, the camera slowly circling. Warm stage light.`
  - `negative_prompt`: `no jerky motion, no limb distortion`
  - `audio`: `<track.mp3 URL>`
- Параметры: `model: wan2.5-i2v-preview`, `duration: 10`, `resolution: 720P`.

**5. (t2v, пейзаж-превиз)** Задача: установочный дрон-план над северным побережьем
- Плохо: `beautiful coast, drone shot, epic, cinematic, masterpiece, 4k` — теги-вайбы без конкретного движения/камеры/света.
- Хорошо:
  - `prompt`: `Aerial drone shot slowly flying forward over a rugged northern coastline at dawn, cold waves breaking against dark cliffs, mist drifting over the water, muted cinematic color grade.`
  - `negative_prompt`: `no sudden camera jumps, no distortion of the cliffs`
- Параметры: `model: wan2.5-t2v-preview`, `duration: 10`, `resolution: 1080P`, `aspect_ratio: 16:9`.
