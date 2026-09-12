"""Higgsfield backend — тонкий клиент generation API (близнец replicate.py/fal.py).

Contract (сверено с docs.higgsfield.ai + /docs/openapi.json И ПРОВЕРЕНО ВЖИВУЮ ключом
Content Factory, 2026-09-12):
- base URL: https://api.higgsfield.ai
- auth header: Authorization: Key <HIGGSFIELD_API_KEY_ID>:<HIGGSFIELD_API_KEY_SECRET>
  (OpenAPI securityScheme authKey = apiKey in header). Живая проверка: без заголовка
  GET /requests/<uuid>/status -> 401 {"detail":"Invalid credentials"}, с заголовком -> 404
  {"detail":"Not found"} — ключ принят.
- submit: POST /{model-path}, где model-path — путь модели ЛЮБОЙ глубины из openapi.json:
  veo3.1 | nano-banana | higgsfield-ai/soul/standard | bytedance/seedance/v1/lite/image-to-video
  | kling-video/v2.5-turbo/pro/text-to-video (всего 48 модельных путей).
  Тело — input ПЛОСКО (никакой обёртки "input"/"params", в отличие от replicate/fal);
  у типовых моделей required = ["prompt"] (+ image_url у i2v). Живая проверка: POST {} на
  higgsfield-ai/soul/v2/standard -> 422 {"detail":[{"loc":["body","prompt"],...}]}.
- ответ submit: {"status":"queued","request_id":<uuid>,"status_url":...,"cancel_url":...};
  poll GET status_url (фолбэк /requests/{id}/status) до терминального статуса.
  Статусы: queued|in_progress (идут) -> completed|failed|nsfw|canceled (терминальные).
- output: отдельного поля "output" НЕТ (в отличие от replicate). Media лежат в типизированных
  полях верхнего уровня рядом с конвертом: images:[{url}], video:{url}, audio:{url},
  audios:[{url}]; часть video/3D-операций добавляет zip/mov/jsx/fbx/ply. Мы отрезаем конверт
  (status/request_id/status_url/cancel_url/error) и отдаём остаток как output.
- ошибки: FastAPI-конверт {"detail": ...}, где detail — строка ИЛИ СПИСОК (422 validation).
- upload: свой upload нужен — data-uri не поддерживаются, только публичные https-URL.
  Два шага: POST /files/generate-upload-url {"content_type"} -> {public_url, upload_url,
  upload_headers}, затем PUT файла на upload_url со ВСЕМИ upload_headers и БЕЗ ключа
  Higgsfield (presigned S3, другой ориджин; ссылка живёт 1 час). В input идёт public_url
  (поля image_url/video_url/audio_url). Живая проверка: generate-upload-url -> 200 с
  presigned S3 и upload_headers {Content-Type, x-amz-tagging}.
  Документированные типы: image/jpeg|jpg|png|webp|gif, audio/wav|x-wav, video/mp4.

Расхождения с изначальным ТЗ:
- SDK-репозиторий higgsfield-ai/higgsfield-client не существует; официальные — higgsfield-py /
  higgsfield-js (docs /how-to/sdk). Контракт взят из docs + openapi.json + живых проб.
- Терминальных статусов не 2, а 4: помимо failed есть nsfw (модерация) и canceled — оба
  трактуем как отказ.
- Квикстарт документирует путь higgsfield-ai/soul/v2/standard, а openapi.json — .../soul/standard;
  живьём отвечают ОБА (422 на пустое тело), поэтому путь модели не сверяется с allowlist'ом
  openapi. При этом nano-banana из openapi.json на нашем аккаунте даёт 404 model_not_found —
  404 означает «нет модели ДЛЯ ЭТОГО аккаунта», а не опечатку в пути.
- Поллинг по рекомендации доков — с мягким бэкоффом (poll_interval -> x1.5 -> потолок 10с).

Единственное публичное исключение — HiggsfieldError; ключ/секрет в текст ошибок не попадают.
"""

from __future__ import annotations

import mimetypes
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from . import _media

DEFAULT_BASE_URL = "https://api.higgsfield.ai"
DEFAULT_TIMEOUT = 180
DEFAULT_POLL_INTERVAL = 3
DEFAULT_DOWNLOAD_TIMEOUT = 120
MAX_POLL_INTERVAL = 10

_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MAX_SEGMENTS = 8
_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_WINDOWS_FILE_MARKER_RE = re.compile(r"^@[A-Za-z]:[\\/]")
_TERMINAL = {"completed", "failed", "nsfw", "canceled"}
_ENVELOPE_KEYS = {"status", "request_id", "status_url", "cancel_url", "error"}
_RESERVED_ROOTS = {"requests", "files"}      # служебные пути API — не модели


class HiggsfieldError(Exception):
    pass


def validate_model(model: str) -> str:
    """model -> нормализованный путь модели ("veo3.1", "bytedance/seedance/v1/lite/...").

    Путь уходит в URL запроса, поэтому пускаем только сегменты вида [A-Za-z0-9][A-Za-z0-9._-]*
    (точка нужна: veo3.1, wan-25-preview). Всё прочее — URL, `..`, `//`, query/fragment,
    служебные корни /requests и /files — отвергается."""
    model = (model or "").strip()
    segments = model.split("/")
    if (model and len(segments) <= _MAX_SEGMENTS
            and all(_SEGMENT_RE.match(s) for s in segments)
            and segments[0] not in _RESERVED_ROOTS):
        return model
    raise HiggsfieldError(
        f"Invalid Higgsfield model {model!r} (expected an API model path such as 'veo3.1' or "
        f"'bytedance/seedance/v1/lite/image-to-video')")


def _redact(text, api_key_id: "str | None" = None, api_key_secret: "str | None" = None) -> str:
    text = str(text)
    for secret in (f"{api_key_id}:{api_key_secret}", api_key_secret, api_key_id):
        if secret and str(secret).strip():
            text = text.replace(str(secret), "***")
    return text


def _headers(api_key_id: "str | None", api_key_secret: "str | None") -> dict:
    if not (api_key_id or "").strip() or not (api_key_secret or "").strip():
        raise HiggsfieldError(
            "Missing HIGGSFIELD_API_KEY_ID/SECRET. Set both HIGGSFIELD_API_KEY_ID and "
            "HIGGSFIELD_API_KEY_SECRET in .env to use Higgsfield.")
    return {"Authorization": f"Key {api_key_id}:{api_key_secret}",
            "Content-Type": "application/json"}


def _request_timeout(timeout: int) -> int:
    return max(1, min(int(timeout or DEFAULT_TIMEOUT), 30))


def _upload_timeout(timeout: int) -> int:
    """Полный таймаут, НЕ клампится как _request_timeout: крупный файл за 30с не пролезет."""
    return max(1, int(timeout or DEFAULT_TIMEOUT))


def _request_error(prefix: str, exc: Exception) -> HiggsfieldError:
    return HiggsfieldError(f"{prefix}: {type(exc).__name__}")  # текст исключения может нести заголовки


def _detail_text(body) -> str:
    """FastAPI-конверт: detail — строка ИЛИ список объектов валидации (422)."""
    if not isinstance(body, dict):
        return ""
    detail = body.get("detail")
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        parts = []
        for item in detail:
            if isinstance(item, dict):
                loc = ".".join(str(p) for p in (item.get("loc") or []))
                msg = str(item.get("msg") or "")
                parts.append(f"{loc}: {msg}" if loc else msg)
            else:
                parts.append(str(item))
        return "; ".join(p for p in parts if p)
    return str(detail) if detail else ""


def _check_status(resp, context: str, api_key_id, api_key_secret) -> None:
    if resp.status_code < 400:
        return
    detail = ""
    try:
        detail = _detail_text(resp.json())
    except ValueError:
        detail = getattr(resp, "text", "") or ""
    msg = f"{context}: HTTP {resp.status_code}"
    if detail:
        msg += f": {_redact(detail, api_key_id, api_key_secret)[:300]}"
    raise HiggsfieldError(msg)


def _json_response(resp, context: str, api_key_id, api_key_secret) -> dict:
    _check_status(resp, context, api_key_id, api_key_secret)
    try:
        obj = resp.json()
    except ValueError as e:
        raise HiggsfieldError(f"{context}: invalid JSON response") from e
    if not isinstance(obj, dict):
        raise HiggsfieldError(f"{context}: expected JSON object response")
    return obj


def _origin(url: str) -> "tuple[str, str, int | None]":
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HiggsfieldError("Higgsfield URL must be absolute http(s)")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as e:
        raise HiggsfieldError("Higgsfield URL has invalid port") from e
    return parsed.scheme, parsed.hostname.lower(), port


def _poll_url(base: str, request: dict, rid: str) -> str:
    """status_url из ответа (строго same-origin с base — туда уходит ключ) или фолбэк."""
    url = request.get("status_url")
    if not url:
        return f"{base}/requests/{rid}/status"
    if _origin(str(url)) != _origin(base):
        raise HiggsfieldError("Higgsfield status URL rejected: cross-origin")
    return str(url)


def _output(request: dict) -> dict:
    """Конверт запроса отрезан — остаётся то, что модель реально вернула (images/video/...)."""
    return {k: v for k, v in request.items() if k not in _ENVELOPE_KEYS}


def upload_file(local_path: "str | Path", *, api_key_id: "str | None",
                api_key_secret: "str | None", base_url: str = DEFAULT_BASE_URL,
                timeout: int = DEFAULT_TIMEOUT, session=None) -> str:
    """Двухшаговая presigned-загрузка; вернуть public_url для url-полей input.

    Шаг 1 — POST /files/generate-upload-url с ключом Higgsfield; шаг 2 — PUT байтов на
    presigned upload_url БЕЗ ключа Higgsfield (чужой ориджин, S3)."""
    headers = _headers(api_key_id, api_key_secret)
    session = session or requests
    base = base_url.rstrip("/")
    p = Path(local_path)
    if not p.is_absolute():
        raise HiggsfieldError(f"Upload path must be absolute: {local_path}")
    if not p.is_file():
        raise HiggsfieldError(f"Upload file not found: {p}")
    content_type, _ = mimetypes.guess_type(str(p))
    if not content_type:
        raise HiggsfieldError(f"Cannot determine MIME type for local file: {p}")
    try:
        payload = p.read_bytes()
    except OSError as e:
        raise HiggsfieldError(f"Cannot read upload file {p}: {type(e).__name__}") from e

    try:
        resp = session.post(f"{base}/files/generate-upload-url", headers=headers,
                            json={"content_type": content_type},
                            timeout=_request_timeout(timeout))
    except requests.exceptions.RequestException as e:
        raise _request_error("Higgsfield upload URL request failed", e) from e
    data = _json_response(resp, "Higgsfield upload URL", api_key_id, api_key_secret)

    upload_url = str(data.get("upload_url") or "")
    public_url = str(data.get("public_url") or "")
    if not upload_url:
        raise HiggsfieldError("Higgsfield upload URL: missing upload_url in response")
    if not public_url:
        raise HiggsfieldError("Higgsfield upload URL: missing public_url in response")
    if urlparse(upload_url).scheme != "https":
        raise HiggsfieldError("Higgsfield presigned upload URL must be https")
    upload_headers = data.get("upload_headers")
    upload_headers = dict(upload_headers) if isinstance(upload_headers, dict) else {}
    upload_headers.pop("Authorization", None)    # ключ Higgsfield в чужое хранилище не уходит
    upload_headers.setdefault("Content-Type", content_type)

    try:
        put = session.put(upload_url, headers=upload_headers, data=payload,
                          timeout=_upload_timeout(timeout))
    except requests.exceptions.RequestException as e:
        raise _request_error("Higgsfield file upload failed", e) from e
    if put.status_code >= 400:
        raise HiggsfieldError(f"Higgsfield file upload: HTTP {put.status_code}")
    return public_url


def resolve_upload_markers(input: dict, *, api_key_id: "str | None",
                           api_key_secret: "str | None", base_url: str = DEFAULT_BASE_URL,
                           timeout: int = DEFAULT_TIMEOUT, session=None) -> dict:
    """Любой @C:/path-маркер в input (на любой глубине) -> upload_file -> public_url.

    Higgsfield принимает только публичные https-URL (data-uri не поддерживаются), поэтому
    локальный файл всегда проходит через presigned-загрузку. Вход копируется, не мутируется;
    не-маркеры (включая "@alice" в prompt) не трогаются."""
    def _walk(obj):
        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_walk(v) for v in obj]
        if isinstance(obj, str) and _WINDOWS_FILE_MARKER_RE.match(obj):
            return upload_file(obj[1:], api_key_id=api_key_id, api_key_secret=api_key_secret,
                               base_url=base_url, timeout=timeout, session=session)
        return obj

    return {k: _walk(v) for k, v in input.items()}


def run(model: str, input: dict, *, api_key_id: "str | None", api_key_secret: "str | None",
        base_url: str = DEFAULT_BASE_URL, timeout: int = DEFAULT_TIMEOUT,
        wait_seconds: "int | float | None" = None,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        download_timeout: int = DEFAULT_DOWNLOAD_TIMEOUT,
        out_dir: "str | Path | None" = None, session=None) -> dict:
    """submit -> poll до терминального статуса -> {"status": "completed", "id", "output",
    "output_urls", ...}; если out_dir — media из output скачиваются (видео/аудио в video/).
    Не уложились в wait_seconds -> {"status": "pending", "id", "poll_url"}."""
    if not isinstance(input, dict):
        raise HiggsfieldError("Higgsfield input must be a JSON object")
    path = validate_model(model)
    headers = _headers(api_key_id, api_key_secret)
    _origin(base_url)
    base = base_url.rstrip("/")
    session = session or requests
    request_timeout = _request_timeout(timeout)

    body = resolve_upload_markers(input, api_key_id=api_key_id, api_key_secret=api_key_secret,
                                  base_url=base, timeout=timeout, session=session)
    try:
        resp = session.post(f"{base}/{path}", headers=headers, json=body,
                            timeout=request_timeout)
    except requests.exceptions.RequestException as e:
        raise _request_error("Higgsfield submit failed", e) from e
    request = _json_response(resp, "Higgsfield submit", api_key_id, api_key_secret)
    rid = str(request.get("request_id") or "")
    if not _ID_RE.match(rid):
        raise HiggsfieldError("Higgsfield submit: missing or invalid request id")
    poll_url = _poll_url(base, request, rid)

    wait_budget = timeout if wait_seconds is None else wait_seconds
    deadline = time.monotonic() + max(0, float(wait_budget))
    status = str(request.get("status") or "queued")
    delay = max(0, float(poll_interval or 0))
    # незнакомый нетерминальный статус считаем «ещё идёт» — оплаченный запуск не бросаем
    while status not in _TERMINAL:
        if time.monotonic() >= deadline:
            return {"status": "pending", "id": rid, "poll_url": poll_url}
        if delay:
            time.sleep(delay)
            delay = min(delay * 1.5, MAX_POLL_INTERVAL)   # бэкофф по рекомендации доков
        try:
            resp = session.get(poll_url, headers=headers, timeout=request_timeout)
        except requests.exceptions.RequestException as e:
            raise _request_error("Higgsfield poll failed", e) from e
        request = _json_response(resp, "Higgsfield poll", api_key_id, api_key_secret)
        status = str(request.get("status") or "")

    if status == "failed":
        error = _redact(request.get("error") or "unknown error", api_key_id, api_key_secret)[:500]
        raise HiggsfieldError(f"Higgsfield request {rid} failed: {error}")
    if status == "nsfw":
        error = _redact(request.get("error") or "", api_key_id, api_key_secret)[:500]
        raise HiggsfieldError(
            f"Higgsfield request {rid} rejected by content moderation (nsfw)"
            + (f": {error}" if error else ""))
    if status == "canceled":
        raise HiggsfieldError(f"Higgsfield request {rid} was canceled")

    output = _output(request)
    refs = _media.collect_keyed_media_refs(output)
    result = {"status": "completed", "id": rid, "output": output,
              "output_urls": [r["url"] for r in refs], "poll_url": poll_url}
    if out_dir is not None:
        result.update(_media.download_media_refs(refs, out_dir, session=session,
                                                 timeout=download_timeout, brand="higgsfield"))
    return result
