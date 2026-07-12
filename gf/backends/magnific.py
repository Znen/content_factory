"""Magnific (Freepik) backend — тонкий HTTP-клиент к Magnific REST API для картинок.

По образцу nano.py: инжектируемый `session` (дефолт requests), MagnificError —
единственное публичное исключение, никакой связи с бюджетом/проектом (это в mcp_server.py).

── КОНТРАКТ API (подтверждён вживую 2026-07-09; расхождения со спекой отмечены) ──
- Host: https://api.magnific.com   Header: x-magnific-api-key   (спека предполагала
  api.freepik.com / x-freepik-api-key — по факту поверхность Magnific).
- Референсы шлются ПРЯМО в теле как base64 (или URL) — отдельный upload-флоу НЕ нужен
  (спека §5.1 предполагала request-upload→PUT→finalize; по факту не требуется).
- POST-пути РАЗЛИЧАЮТСЯ по моделям:
    mystic              -> POST /v1/ai/mystic                            (t2i, рефы опциональны)
    seedream-v4-5-edit  -> POST /v1/ai/text-to-image/seedream-v4-5-edit  (reference_images[], 1-5)
    flux-kontext-pro    -> POST /v1/ai/text-to-image/flux-kontext-pro    (input_image, ровно 1)
    nano-banana-pro     -> POST /v1/ai/text-to-image/nano-banana-pro     (reference_images[], 0-4;
                           t2i или multi-ref; verified live 2026-07-09)
- Async: POST -> {"data":{"task_id","status":"CREATED","generated":[]}}.
  Поллинг: GET <post-path>/{task_id} -> data.status в CREATED|IN_PROGRESS|COMPLETED|FAILED,
  готовые картинки в data.generated[] (подписанные CDN-URL freepik, качаются GET без ключа).
- aspect_ratio — формат ЗАВИСИТ ОТ МОДЕЛИ: mystic/seedream/flux — свой enum Magnific
  (square_1_1, widescreen_16_9, social_story_9_16, …); nano-banana-pro — ОБЫЧНЫЙ формат
  ("1:1", "16:9", "9:16", "2:3"…). Передаётся как есть; пустой — не передаётся.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import time
from pathlib import Path

import requests

DEFAULT_TIMEOUT = 180
# суффикс → MIME (nano-banana-pro требует mime_type в каждом объекте reference_images)
SUPPORTED_INPUT_MIMES = {
    ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".webp": "image/webp",
}

# per-model маршрутизация (подтверждено вживую). ref_item — формат ЭЛЕМЕНТА reference_images:
#   "string" — голая base64-строка (seedream ждёт список строк);
#   "object" — {image, mime_type} (nano-banana-pro: голые строки → 400 "valid dictionary").
_MODELS = {
    "mystic": {"path": "/v1/ai/mystic", "ref_field": None},
    "seedream-v4-5-edit": {"path": "/v1/ai/text-to-image/seedream-v4-5-edit",
                           "ref_field": "reference_images", "ref_mode": "array",
                           "ref_item": "string", "ref_min": 1, "ref_max": 5},
    "flux-kontext-pro": {"path": "/v1/ai/text-to-image/flux-kontext-pro",
                         "ref_field": "input_image", "ref_mode": "single",
                         "ref_item": "string", "ref_min": 1, "ref_max": 1},
    "nano-banana-pro": {"path": "/v1/ai/text-to-image/nano-banana-pro",
                        "ref_field": "reference_images", "ref_mode": "array",
                        "ref_item": "object",   # {image, mime_type}, НЕ голая строка
                        "ref_min": 0, "ref_max": 4},   # рефы опциональны (умеет t2i и multi-ref)
}


# видео-модели Magnific (контракт подтверждён probe'ом 2026-07-09):
# veo — t2v (без стартового кадра); kling — i2v (поле кадра `image`, НЕ image_url!).
# duration/aspect enums РАЗНЫЕ по моделям (сверено с live-валидатором).
_VIDEO_MODELS = {
    "veo-3-1": {"path": "/v1/ai/text-to-video/veo-3-1", "mode": "t2v", "img_field": None,
                "durations": {4, 6, 8}, "aspects": {"16:9", "9:16"}},
    "kling-v2-5-pro": {"path": "/v1/ai/image-to-video/kling-v2-5-pro", "mode": "i2v",
                       "img_field": "image", "durations": {"5", "10"},
                       "aspects": {"square_1_1", "social_story_9_16", "widescreen_16_9"}},
    # соседи kling — та же схема, другой путь (дефолт — v2-5-pro; у неё есть паспорт)
    "kling-v2-6-pro": {"path": "/v1/ai/image-to-video/kling-v2-6-pro", "mode": "i2v",
                       "img_field": "image", "durations": {"5", "10"},
                       "aspects": {"square_1_1", "social_story_9_16", "widescreen_16_9"}},
    "kling-v2-1-pro": {"path": "/v1/ai/image-to-video/kling-v2-1-pro", "mode": "i2v",
                       "img_field": "image", "durations": {"5", "10"},
                       "aspects": {"square_1_1", "social_story_9_16", "widescreen_16_9"}},
    "kling-pro": {"path": "/v1/ai/image-to-video/kling-pro", "mode": "i2v",
                  "img_field": "image", "durations": {"5", "10"},
                  "aspects": {"square_1_1", "social_story_9_16", "widescreen_16_9"}},
}


class MagnificError(Exception):
    pass


def _ref_mime(p: Path) -> str:
    """Суффикс файла → MIME; неизвестный тип → MagnificError."""
    mime = SUPPORTED_INPUT_MIMES.get(p.suffix.lower())
    if not mime:
        raise MagnificError(
            f"Unsupported reference type: {p.name} (supported: {sorted(SUPPORTED_INPUT_MIMES)})")
    return mime


def encode_ref(path: "str | Path") -> str:
    """Локальный файл-картинку → base64-строку (для reference_images/input_image)."""
    p = Path(path)
    if not p.exists():
        raise MagnificError(f"Reference file not found: {p}")
    _ref_mime(p)   # валидация типа (сообщение как раньше)
    return base64.b64encode(p.read_bytes()).decode("ascii")


def encode_ref_object(path: "str | Path") -> dict:
    """Локальный файл → {"image": base64, "mime_type": mime} (nano-banana-pro reference_images)."""
    p = Path(path)
    if not p.exists():
        raise MagnificError(f"Reference file not found: {p}")
    return {"image": base64.b64encode(p.read_bytes()).decode("ascii"), "mime_type": _ref_mime(p)}


def _build_payload(model: str, prompt: str, refs: "list", aspect: str = "") -> "tuple[str, dict]":
    """Собрать (post_path, json_body) под конкретную модель. Референсы — base64 в теле."""
    cfg = _MODELS.get(model)
    if cfg is None:
        raise MagnificError(f"Unknown Magnific model {model!r} (known: {sorted(_MODELS)})")
    refs = list(refs or [])
    body = {"prompt": prompt}
    if aspect:
        body["aspect_ratio"] = aspect

    field = cfg["ref_field"]
    if field is None:
        if refs:
            raise MagnificError(
                f"Модель {model} — t2i без референсов; для лицо+локация используй seedream-v4-5-edit")
    else:
        lo, hi = cfg["ref_min"], cfg["ref_max"]
        if not (lo <= len(refs) <= hi):
            raise MagnificError(
                f"Модель {model} требует {lo}-{hi} референс(ов), получено {len(refs)}")
        # формат элемента per-model: object → {image, mime_type}; string → голый base64
        enc = encode_ref_object if cfg.get("ref_item") == "object" else encode_ref
        encoded = [enc(r) for r in refs]
        if encoded:   # пустой список рефов (ref_min=0, t2i) — поле не добавляем вовсе
            body[field] = encoded if cfg["ref_mode"] == "array" else encoded[0]
    return cfg["path"], body


DEFAULT_DOWNLOAD_TIMEOUT = 120
DEFAULT_DOWNLOAD_RETRIES = 3


def _resolve_image_arg(image: str) -> str:
    """Стартовый кадр kling: локальный файл → base64; URL/data-uri/base64 → как есть.
    ⚠️ приём base64/data-uri для видео на генерации не подтверждён безопасно — надёжный путь
    для локального winner'а: сначала выложить кадр как публичный/CDN-URL. См. паспорт/DoD."""
    p = Path(image)
    try:
        is_local = p.exists() and p.is_file()
    except OSError:
        is_local = False
    return encode_ref(p) if is_local else image


def _build_video_payload(model: str, prompt: str, *, negative: str = "", duration=None,
                         aspect: str = "", image: str = "") -> "tuple[str, dict]":
    """Собрать (post_path, json_body) для видео-модели. duration/aspect enums различаются по модели."""
    cfg = _VIDEO_MODELS.get(model)
    if cfg is None:
        raise MagnificError(f"Unknown Magnific video model {model!r} (known: {sorted(_VIDEO_MODELS)})")
    body = {"prompt": prompt}
    if negative:
        body["negative_prompt"] = negative
    if duration is not None and duration != "":
        if duration not in cfg["durations"]:
            raise MagnificError(
                f"{model}: duration должен быть {sorted(cfg['durations'], key=str)}, получено {duration!r}")
        body["duration"] = duration
    if aspect:
        if aspect not in cfg["aspects"]:
            raise MagnificError(
                f"{model}: aspect_ratio должен быть {sorted(cfg['aspects'])}, получено {aspect!r}")
        body["aspect_ratio"] = aspect
    if cfg["img_field"]:
        if not image:
            raise MagnificError(f"Модель {model} — i2v, нужен стартовый кадр (image)")
        body[cfg["img_field"]] = _resolve_image_arg(image)
    elif image:
        raise MagnificError(f"Модель {model} — t2v без стартового кадра (image не принимается)")
    return cfg["path"], body


def save_image(url: str, out_path: Path, session=None, *,
               timeout: int = DEFAULT_DOWNLOAD_TIMEOUT, retries: int = DEFAULT_DOWNLOAD_RETRIES,
               _sleep=None) -> int:
    """Скачать готовую картинку по подписанному CDN-URL (без auth-заголовка). Вернуть размер.

    CDN freepik бывает медленным → ретрай с backoff (паттерн как в backends/dreamina.py),
    чтобы не терять уже оплаченный результат из-за одного таймаута. При исчерпании попыток —
    MagnificError (вызывающая generate() ловит и пробрасывает URL наверх, а не теряет)."""
    import time
    session = session or requests
    _sleep = _sleep or time.sleep
    last = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            r = session.get(url, timeout=timeout)
            if r.status_code == 200:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(r.content)
                return len(r.content)
            last = MagnificError(f"Скачивание результата: HTTP {r.status_code}")
        except requests.exceptions.RequestException as e:
            last = MagnificError(f"Не удалось скачать результат Magnific: {e}")
        if attempt < retries:
            _sleep(1.5 * attempt)
    raise last


def _stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _submit(session, base_url, path, api_key, body, timeout) -> dict:
    url = f"{base_url.rstrip('/')}{path}"
    headers = {"x-magnific-api-key": api_key, "Content-Type": "application/json"}
    try:
        r = session.post(url, headers=headers, json=body, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise MagnificError(f"Не удалось достучаться до Magnific ({url}): {e}") from e
    if r.status_code == 401:
        raise MagnificError("Magnific: неверный API-ключ (401). Проверь GF_MAGNIFIC_API_KEY.")
    if r.status_code in (402, 403):
        raise MagnificError(f"Magnific: нет доступа/кредитов (HTTP {r.status_code}): {r.text[:200]}")
    if r.status_code != 200:
        raise MagnificError(f"Magnific POST {path}: HTTP {r.status_code} {r.text[:200]}")
    try:
        return r.json()["data"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise MagnificError(f"Magnific: неожиданный ответ на POST: {r.text[:200]}") from e


def _poll_once(session, base_url, path, api_key, task_id, timeout) -> dict:
    url = f"{base_url.rstrip('/')}{path}/{task_id}"
    headers = {"x-magnific-api-key": api_key}
    try:
        r = session.get(url, headers=headers, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise MagnificError(f"Magnific poll недоступен: {e}") from e
    if r.status_code != 200:
        raise MagnificError(f"Magnific poll {task_id}: HTTP {r.status_code} {r.text[:200]}")
    try:
        return r.json()["data"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise MagnificError(f"Magnific: неожиданный ответ на poll: {r.text[:200]}") from e


def generate(prompt: str, refs: "list", out_dir: "str | Path", *, model: str,
             base_url: str, api_key: "str | None", aspect: str = "",
             timeout: int = DEFAULT_TIMEOUT, poll_interval: int = 3,
             download_timeout: int = DEFAULT_DOWNLOAD_TIMEOUT,
             download_retries: int = DEFAULT_DOWNLOAD_RETRIES,
             session=None) -> dict:
    """Полный цикл: собрать payload (base64-рефы) → POST → поллинг → скачать картинку.
    Возвращает {"images": [Path,...], "task_id": str, "timed_out": bool}.
    Если задача COMPLETED, но скачивание с CDN упало (после ретраев) — результат НЕ теряется:
    в ответе появляются "image_urls" (несохранённые CDN-URL) + "download_failed": True.
    timeout истёк, задача жива → timed_out=True + task_id (вызывающий отдаёт «номерок»)."""
    if not api_key:
        raise MagnificError("Нет GF_MAGNIFIC_API_KEY — укажи ключ Magnific в .env.")
    session = session or requests
    path, body = _build_payload(model, prompt, refs, aspect)

    data = _submit(session, base_url, path, api_key, body, timeout)
    task_id = data.get("task_id")
    status = data.get("status", "")

    deadline = time.time() + timeout
    while status in ("CREATED", "IN_PROGRESS"):
        if time.time() >= deadline:
            return {"images": [], "task_id": task_id, "timed_out": True}
        if poll_interval:
            time.sleep(poll_interval)
        data = _poll_once(session, base_url, path, api_key, task_id, timeout)
        status = data.get("status", "")

    if status == "FAILED":
        raise MagnificError(f"Magnific задача {task_id} провалилась: {data}")
    urls = data.get("generated") or []
    if not urls:
        raise MagnificError(f"Magnific: статус {status}, но нет картинок в generated[]")

    out_dir = Path(out_dir)
    stamp = _stamp()
    saved, failed_urls = [], []
    for i, url in enumerate(urls, start=1):
        suffix = "" if len(urls) == 1 else f"-{i:02d}"
        out_path = out_dir / f"magnific_{model}_{stamp}{suffix}.png"
        try:
            save_image(url, out_path, session=session, timeout=download_timeout,
                       retries=download_retries)
            saved.append(out_path)
        except MagnificError:
            failed_urls.append(url)   # оплаченный результат жив на CDN — не теряем URL
    result = {"images": saved, "task_id": task_id, "timed_out": False}
    if failed_urls:
        result["image_urls"] = failed_urls
        result["download_failed"] = True
    return result


def generate_video(prompt: str, out_dir: "str | Path", *, model: str, base_url: str,
                   api_key: "str | None", negative: str = "", duration=None, aspect: str = "",
                   image: str = "", timeout: int = DEFAULT_TIMEOUT, poll_interval: int = 3,
                   download_timeout: int = DEFAULT_DOWNLOAD_TIMEOUT,
                   download_retries: int = DEFAULT_DOWNLOAD_RETRIES, session=None) -> dict:
    """Видео через Magnific REST (t2v veo / i2v kling). Реюз поллинга и CDN-ретрая картинок.
    Возвращает {"videos": [Path,...], "task_id", "timed_out"}; при упавшем скачивании
    COMPLETED-задачи — video_urls + download_failed (результат не теряется)."""
    if not api_key:
        raise MagnificError("Нет GF_MAGNIFIC_API_KEY — укажи ключ Magnific в .env.")
    session = session or requests
    path, body = _build_video_payload(model, prompt, negative=negative, duration=duration,
                                      aspect=aspect, image=image)

    data = _submit(session, base_url, path, api_key, body, timeout)
    task_id = data.get("task_id")
    status = data.get("status", "")

    deadline = time.time() + timeout
    while status in ("CREATED", "IN_PROGRESS"):
        if time.time() >= deadline:
            return {"videos": [], "task_id": task_id, "timed_out": True}
        if poll_interval:
            time.sleep(poll_interval)
        data = _poll_once(session, base_url, path, api_key, task_id, timeout)
        status = data.get("status", "")

    if status == "FAILED":
        raise MagnificError(f"Magnific видео-задача {task_id} провалилась: {data}")
    urls = data.get("generated") or []
    if not urls:
        raise MagnificError(f"Magnific: статус {status}, но нет видео в generated[]")

    out_dir = Path(out_dir)
    stamp = _stamp()
    saved, failed_urls = [], []
    for i, url in enumerate(urls, start=1):
        suffix = "" if len(urls) == 1 else f"-{i:02d}"
        out_path = out_dir / f"magnific_{model}_{stamp}{suffix}.mp4"
        try:
            save_image(url, out_path, session=session, timeout=download_timeout,
                       retries=download_retries)
            saved.append(out_path)
        except MagnificError:
            failed_urls.append(url)
    result = {"videos": saved, "task_id": task_id, "timed_out": False}
    if failed_urls:
        result["video_urls"] = failed_urls
        result["download_failed"] = True
    return result
