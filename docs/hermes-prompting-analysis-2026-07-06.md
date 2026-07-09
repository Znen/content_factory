# Как Hermes пишет промпты для генерации контента — анализ (2026-07-06)

**Назначение:** фактура для проектирования слоя prompt-writer в Content Factory.
**Метод:** разбор кода агента (%LOCALAPPDATA%\hermes\hermes-agent), config.yaml, SOUL.md, всех creative-скиллов и реальных промптов из сессий 2026-07-05..06 (проект Ryaba).

## TL;DR

Все промпты пишет **основная модель агента — deepseek-v4-pro**. Специализированного промпт-райтера нет ни в виде auxiliary-роли, ни в виде инструмента. Знания о промптинге существуют и местами отличные, но они (а) разбросаны по 8+ скиллам, (б) попадают в контекст только если deepseek сам догадается открыть нужный скилл, (в) исполняются с нарушениями даже когда скилл загружен. Промпт нигде не обогащается по пути: `image_generate`, инструменты Magnific и `gf_generate_*` передают строку в модель дословно.

## 1. Механизм: кто и по каким знаниям пишет промпт

- **Автор промпта:** deepseek-v4-pro (config.yaml:1-5). Auxiliary-роли (vision=claude-sonnet-4-6, web_extract/compression=gemini-2.5-flash, и т.д., config.yaml:162-240) промпты не трогают. Роли «prompt-writer» нет.
- **Уровень 1 — всегда в системном промпте:** индекс скиллов «имя + 1 строка описания» (prompt_builder.py:1040-1271) + общие правила из SOUL.md:34-38 («промпты на английском, фиксируй ракурс/свет/движение/формат/референсы», aspect ratio для image_generate).
- **Уровень 2 — по требованию:** полный SKILL.md подтягивается только явным вызовом `skill_view(name)`. Система предписывает это как mandatory, но решение принимает сам deepseek — по одной строке описания в индексе.
- **Обогащения нет:** google-провайдер image_generate шлёт prompt дословно (plugins/image_gen/google/__init__.py:222-226); gf_generate_draft/final принимают prompt строкой; инструменты Magnific — тоже. Единственное исключение: FAL FLUX-апскейл дописывает "masterpiece, best quality, highres" (image_generation_tool.py:560-603) — не активный путь.
- **Самообучение есть:** фоновый review-процесс (whitelist: только memory/skill-инструменты) дописывает проверенные уроки прямо в SKILL.md (пример 2026-07-06: «two refs beat three» в magnific-mcp). База знаний живая, но растёт как куча pitfalls, а не как структурированные правила per-model.

## 2. Четыре пути генерации (и где в каждом рождается промпт)

| Путь | Кто пишет промпт | Знания | Замечания |
|---|---|---|---|
| `image_generate` (встроенный, google direct → gemini-2.5-flash-image) | deepseek в момент вызова | SOUL.md + скилл если открыт | prompt дословно в Gemini |
| Magnific MCP (`images_generate`, видео, TTS) | deepseek; часто промпт зашит в **ad-hoc Python-скрипт** (direct MCP client) | magnific-mcp SKILL.md (pitfalls) | скрипты одноразовые, промпт нигде не сохраняется |
| Content Factory `gf_generate_draft/final` | deepseek (prompt — параметр) | ничего специфичного | **ни разу не использован в бою** — нет ни одного .gf_cost_log.jsonl ни в одном проекте |
| Cron-джобы (напр. «stereovombat daily 12:00») | стилевые указания зашиты в текст cron-промпта («pixel art, киберпанк, тёмная палитра…»), деталировку дописывает deepseek | тело cron-джоба | знания о стиле дублируются в каждом джобе |

## 3. Реальные промпты (Ryaba, 2026-07-05..06) — что получается

Пример (Magnific `images_generate`, model=imagen-nano-banana-2 / mode seedream-4-5, 3 референса):

> Generate a photorealistic image. COMPOSITION from Image 1: follow this exact lineart composition. … DOYPACK from Image 2: the mayonnaise doypack MUST have this exact design with Ryaba brand… LIGHTING from Image 3: warm summer afternoon sunlight… Photorealistic DSLR quality. NO curtain, NO CGI, NO plastic skin, NO fake HDR.

Оценка: структура ролей референсов — правильная идея (из скиллов). Но:

1. **Нарушена собственная база знаний:** скилл magnific-mcp требует `@img1/@img2`-нотацию как ОБЯЗАТЕЛЬНУЮ (из документации Google) — deepseek пишет «Image 1/2/3».
2. **«Negative:» текстом в моделях без негативов:** Gemini/Nano Banana не имеют negative-параметра; «NO curtain, NO CGI» в теле промпта прямо нарушает golden rule позитивного обрамления из гайда Google («empty street», а не «no cars»). Слово «curtain» в промпте *повышает* вероятность занавески.
3. **CAPS-давление вместо точности** («MUST», «EXACTLY», «CRITICAL») — компенсация слабого контроля, гайдами не предусмотрено.
4. **Дорогие итерации:** v1–v3 с 3 референсами — composition drift, победил v4 с 2 референсами. 50 кредитов за генерацию seedream; урок задним числом записан в скилл, но потрачен на трату.
5. **Промпты не персистятся:** живут в одноразовых tmp-скриптах и логах; Фаза 2 фабрики (prompt sidecars) не реализована.

## 4. Карта знаний о промптинге (что уже есть, что переиспользовать)

| Модель/площадка | Где знания | Полнота |
|---|---|---|
| Gemini / Nano Banana (edit) | `nitro-banana/SKILL.md` (KEEP/EDIT-структура, TRANSFORM-lineart, ограничения: не умеет chroma key, DSLR-фотореализм, проценты размеров) | **очень высокая** |
| Nano Banana каноника Google | `nitro-banana-generation/references/nano-banana-prompting-guide.md` (Core Formula: Subject+Action+Location+Composition+Style; golden rules; @img; камера; текст в кавычках; 80-150 символов) | **высокая, каноническая** |
| Magnific nano-banana-2 / seedream | `magnific-mcp/SKILL.md` pitfalls + `templates/three-ref-storyboard-prompt.md` | высокая, но размазана |
| Lineart-стиль | `storyboard-lineart` + `ai-keyframe-workflow` (STRICTLY B&W-блок, continuity, короткий промпт лучше длинного) | высокая (узкая) |
| Kling / Seedance 2.0 (видео) | `magnific-mcp/SKILL.md` — механика clips[]/keyframes, чуть-чуть примеров | средняя |
| Veo 3.1, TTS ElevenLabs | только API-вызовы | **почти ноль** |
| ComfyUI / SDXL (черновики фабрики!) | `comfyui/SKILL.md` — только denoise-инсайты; ни слова о теговом синтаксисе SDXL, весах, негативах | **почти ноль** |
| Imagen 3/4, Flux, GPT Image (FAL-каталог) | список слагов | ноль |

**Критичный разрыв для фабрики:** её черновиковый бэкенд — SDXL (juggernautxl), который требует принципиально другого стиля промпта (теги/веса/настоящий negative-параметр), чем натуральный язык Gemini. Гайда нет вообще → deepseek пишет SDXL-промпты «по-геминиевски».

## 5. Слабые места текущей схемы (ранжировано)

1. **Вероятностная доставка знаний:** правильный промпт требует цепочки «описание скилла в индексе триггернуло → deepseek открыл скилл → нашёл правило среди pitfalls → применил». Обрыв любого звена = посредственный промпт. Сегодняшние примеры показывают обрывы даже при загруженном скилле.
2. **Нет адаптации под модель:** один автор пишет для SDXL, Gemini, Seedream, Kling одним стилем; негативы суёт туда, где их не существует.
3. **Знания фрагментированы и дублируются** по 8 скиллам с расхождениями (таблица «3 референса» против свежего урока «2 референса» — сегодня поправлено в одном месте, копии в других скиллах могли остаться).
4. **Нет персистенса промптов** (side-cars) → нет накопления удачных промптов per-project, «память процесса» из ИДЕИ фабрики не работает.
5. **Пробелы в знаниях:** SDXL, видео-модели, TTS, Imagen/Flux/Seedream.
6. **gf-фабрика в обход:** реальная генерация идёт мимо неё (magnific напрямую, ad-hoc скрипты) — слой в gf сам по себе не перехватит эти пути, пока Hermes не начнёт ходить через фабрику.

## 6. Входные данные для проектирования prompt-writer

- Готовые «пакеты знаний» per-model можно собрать из существующих файлов (см. §4) — их стоит вынести из скиллов в базу слоя, ключевать по слагу модели (`imagen-nano-banana-2`, `seedream-4-5`, `sdxl`, `kling-omni3`…).
- Интерфейсу слоя понадобится на вход: намерение + тип задачи (t2i/edit/lineart/video/tts) + слаг модели + референсы с ролями + проектный контекст (бренд-факты типа «Ряба, не Рада»); на выход: prompt (+ настоящий negative только для бэкендов, где он есть) + параметры (aspect, resolution).
- Дописать недостающие гайды: SDXL-теговый стиль (черновики), Kling/Seedance/Veo, TTS.
- Учесть пути в обход фабрики (magnific напрямую, image_generate, cron) — иначе слой покроет только неиспользуемый gf.
- Механизм самообучения (background review → skill patch) стоит перенаправить: уроки писать в базу знаний слоя, а не в разрастающиеся SKILL.md.
