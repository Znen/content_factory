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
SUPPORTED_INPUT_MIMES = {".png", ".jpg", ".jpeg", ".webp"}

# per-model маршрутизация (подтверждено вживую)
_MODELS = {
    "mystic": {"path": "/v1/ai/mystic", "ref_field": None},
    "seedream-v4-5-edit": {"path": "/v1/ai/text-to-image/seedream-v4-5-edit",
                           "ref_field": "reference_images", "ref_mode": "array",
                           "ref_min": 1, "ref_max": 5},
    "flux-kontext-pro": {"path": "/v1/ai/text-to-image/flux-kontext-pro",
                         "ref_field": "input_image", "ref_mode": "single",
                         "ref_min": 1, "ref_max": 1},
    "nano-banana-pro": {"path": "/v1/ai/text-to-image/nano-banana-pro",
                        "ref_field": "reference_images", "ref_mode": "array",
                        "ref_min": 0, "ref_max": 4},   # рефы опциональны (умеет t2i и multi-ref)
}


class MagnificError(Exception):
    pass


def encode_ref(path: "str | Path") -> str:
    """Локальный файл-картинку → base64-строку (для reference_images/input_image)."""
    p = Path(path)
    if not p.exists():
        raise MagnificError(f"Reference file not found: {p}")
    if p.suffix.lower() not in SUPPORTED_INPUT_MIMES:
        raise MagnificError(
            f"Unsupported reference type: {p.name} (supported: {sorted(SUPPORTED_INPUT_MIMES)})")
    return base64.b64encode(p.read_bytes()).decode("ascii")


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
        encoded = [encode_ref(r) for r in refs]
        if encoded:   # пустой список рефов (ref_min=0, t2i) — поле не добавляем вовсе
            body[field] = encoded if cfg["ref_mode"] == "array" else encoded[0]
    return cfg["path"], body


def save_image(url: str, out_path: Path, session=None) -> int:
    """Скачать готовую картинку по подписанному CDN-URL (без auth-заголовка). Вернуть размер."""
    session = session or requests
    try:
        r = session.get(url, timeout=60)
    except requests.exceptions.RequestException as e:
        raise MagnificError(f"Не удалось скачать результат Magnific: {e}") from e
    if r.status_code != 200:
        raise MagnificError(f"Скачивание результата: HTTP {r.status_code}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)
    return len(r.content)


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
             session=None) -> dict:
    """Полный цикл: собрать payload (base64-рефы) → POST → поллинг → скачать картинку.
    Возвращает {"images": [Path,...], "task_id": str, "timed_out": bool}.
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
    saved = []
    for i, url in enumerate(urls, start=1):
        suffix = "" if len(urls) == 1 else f"-{i:02d}"
        out_path = out_dir / f"magnific_{model}_{stamp}{suffix}.png"
        save_image(url, out_path, session=session)
        saved.append(out_path)
    return {"images": saved, "task_id": task_id, "timed_out": False}
