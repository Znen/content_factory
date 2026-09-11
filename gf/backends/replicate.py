"""Replicate backend — тонкий клиент predictions API + Files API (близнец fal.py).

Contract (сверено с docs + OpenAPI api.replicate.com, 2026-09):
- auth header: Authorization: Bearer <REPLICATE_API_TOKEN> (OpenAPI securityScheme = bearer;
  легаси-форма "Token <...>" в доках встречается, но основная — Bearer)
- submit по формату model:
    <64-hex version>            -> POST /v1/predictions  {"version": hash, "input": {...}}
    owner/name:<64-hex version> -> POST /v1/predictions  {"version": hash, "input": {...}}
    owner/name                  -> POST /v1/models/{owner}/{name}/predictions  {"input": {...}}
- ответ {"id","status","urls":{"get","cancel",...}}; poll GET urls.get
  (фолбэк /v1/predictions/{id}) до succeeded|failed|canceled (идут starting|processing).
  output лежит прямо в prediction (не отдельный response_url, как у fal).
- files: POST /v1/files, multipart: content=(filename, bytes, type) + filename (обязателен) + type;
  ответ 201 {"urls":{"get": URL}} — этот URL и уходит в input модели.

Единственное публичное исключение — ReplicateError; токен в текст ошибок не попадает никогда.
"""

from __future__ import annotations

import mimetypes
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from . import _media

DEFAULT_API_URL = "https://api.replicate.com"
DEFAULT_TIMEOUT = 180
DEFAULT_POLL_INTERVAL = 3
DEFAULT_DOWNLOAD_TIMEOUT = 120

_VERSION_RE = re.compile(r"^[0-9a-f]{64}$")
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ID_RE = re.compile(r"^[A-Za-z0-9]+$")
_WINDOWS_FILE_MARKER_RE = re.compile(r"^@[A-Za-z]:[\\/]")
_TERMINAL = {"succeeded", "failed", "canceled"}


class ReplicateError(Exception):
    pass


def validate_model(model: str) -> "tuple[str, str | None, str | None]":
    """model -> (kind, owner/name | None, version | None); kind: "version" | "model".

    Всё, что не owner/name[:<64-hex>] и не голый 64-hex, отвергается (URL, `..`, `//`,
    лишние сегменты, query) — model уходит в путь запроса, инъекции туда не пускаем."""
    model = (model or "").strip()
    if _VERSION_RE.match(model):
        return "version", None, model
    ref, sep, version = model.partition(":")
    parts = ref.split("/")
    if len(parts) == 2 and all(_SLUG_RE.match(p) for p in parts):
        if not sep:
            return "model", ref, None
        if _VERSION_RE.match(version):
            return "version", ref, version
    raise ReplicateError(
        f"Invalid Replicate model {model!r} (expected owner/name, owner/name:<64-hex version> "
        f"or <64-hex version>)")


def _redact(text: str, api_key: "str | None") -> str:
    text = str(text)
    return text.replace(api_key, "***") if api_key else text


def _auth(api_key: "str | None") -> dict:
    if not api_key:
        raise ReplicateError(
            "Missing REPLICATE_API_TOKEN. Set REPLICATE_API_TOKEN in .env to use Replicate.")
    return {"Authorization": f"Bearer {api_key}"}


def _request_timeout(timeout: int) -> int:
    return max(1, min(int(timeout or DEFAULT_TIMEOUT), 30))


def _upload_timeout(timeout: int) -> int:
    """Полный таймаут, НЕ клампится как _request_timeout: крупный файл за 30с не пролезет."""
    return max(1, int(timeout or DEFAULT_TIMEOUT))


def _request_error(prefix: str, exc: Exception) -> ReplicateError:
    return ReplicateError(f"{prefix}: {type(exc).__name__}")   # текст исключения может нести заголовки


def _json_response(resp, context: str, api_key: "str | None") -> dict:
    if resp.status_code >= 400:
        detail = ""
        try:
            body = resp.json()
            if isinstance(body, dict):
                detail = str(body.get("detail") or body.get("title") or "")
        except ValueError:
            pass
        msg = f"{context}: HTTP {resp.status_code}"
        if detail:
            msg += f": {_redact(detail, api_key)[:300]}"
        raise ReplicateError(msg)
    try:
        obj = resp.json()
    except ValueError as e:
        raise ReplicateError(f"{context}: invalid JSON response") from e
    if not isinstance(obj, dict):
        raise ReplicateError(f"{context}: expected JSON object response")
    return obj


def _origin(url: str) -> "tuple[str, str, int | None]":
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ReplicateError("Replicate URL must be absolute http(s)")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as e:
        raise ReplicateError("Replicate URL has invalid port") from e
    return parsed.scheme, parsed.hostname.lower(), port


def _poll_url(base: str, prediction: dict, pid: str) -> str:
    """urls.get из ответа (строго same-origin с api_url — туда уходит токен) или фолбэк."""
    url = (prediction.get("urls") or {}).get("get")
    if not url:
        return f"{base}/v1/predictions/{pid}"
    if _origin(url) != _origin(base):
        raise ReplicateError("Replicate poll URL rejected: cross-origin")
    return url


def upload_file(local_path: "str | Path", *, api_key: "str | None",
                api_url: str = DEFAULT_API_URL, timeout: int = DEFAULT_TIMEOUT,
                session=None) -> str:
    """Загрузить локальный файл в Replicate Files API; вернуть urls.get для input модели."""
    headers = _auth(api_key)
    session = session or requests
    p = Path(local_path)
    if not p.is_absolute():
        raise ReplicateError(f"Upload path must be absolute: {local_path}")
    if not p.is_file():
        raise ReplicateError(f"Upload file not found: {p}")
    content_type, _ = mimetypes.guess_type(str(p))
    if not content_type:
        raise ReplicateError(f"Cannot determine MIME type for local file: {p}")
    try:
        payload = p.read_bytes()
    except OSError as e:
        raise ReplicateError(f"Cannot read upload file {p}: {type(e).__name__}") from e
    try:
        # multipart: Content-Type с boundary ставит requests сам — json-заголовок тут не нужен
        resp = session.post(f"{api_url.rstrip('/')}/v1/files", headers=headers,
                            files={"content": (p.name, payload, content_type)},
                            data={"filename": p.name, "type": content_type},
                            timeout=_upload_timeout(timeout))
    except requests.exceptions.RequestException as e:
        raise _request_error("Replicate file upload failed", e) from e
    data = _json_response(resp, "Replicate file upload", api_key)
    url = (data.get("urls") or {}).get("get")
    if not url:
        raise ReplicateError("Replicate file upload: missing urls.get in response")
    return str(url)


def resolve_upload_markers(input: dict, *, api_key: "str | None",
                           api_url: str = DEFAULT_API_URL, timeout: int = DEFAULT_TIMEOUT,
                           session=None) -> dict:
    """Любой @C:/path-маркер в input (на любой глубине) -> upload_file -> URL.

    Replicate принимает URL в любом поле, поэтому, в отличие от fal, отдельных url-полей нет.
    Вход копируется, не мутируется; не-маркеры (включая "@alice" в prompt) не трогаются."""
    def _walk(obj):
        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_walk(v) for v in obj]
        if isinstance(obj, str) and _WINDOWS_FILE_MARKER_RE.match(obj):
            return upload_file(obj[1:], api_key=api_key, api_url=api_url, timeout=timeout,
                               session=session)
        return obj

    return {k: _walk(v) for k, v in input.items()}


def run(model: str, input: dict, *, api_key: "str | None", api_url: str = DEFAULT_API_URL,
        timeout: int = DEFAULT_TIMEOUT, wait_seconds: "int | float | None" = None,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        download_timeout: int = DEFAULT_DOWNLOAD_TIMEOUT,
        out_dir: "str | Path | None" = None, session=None) -> dict:
    """submit -> poll до терминального статуса -> {"status": "completed", "id", "output",
    "output_urls", ...}; если out_dir — media из output скачиваются (видео/аудио в video/).
    Не уложились в wait_seconds -> {"status": "pending", "id", "poll_url"}."""
    if not isinstance(input, dict):
        raise ReplicateError("Replicate input must be a JSON object")
    kind, ref, version = validate_model(model)
    headers = {**_auth(api_key), "Content-Type": "application/json"}
    _origin(api_url)
    base = api_url.rstrip("/")
    session = session or requests
    request_timeout = _request_timeout(timeout)

    input = resolve_upload_markers(input, api_key=api_key, api_url=base, timeout=timeout,
                                   session=session)
    if kind == "version":
        submit_url, body = f"{base}/v1/predictions", {"version": version, "input": input}
    else:
        submit_url, body = f"{base}/v1/models/{ref}/predictions", {"input": input}
    try:
        resp = session.post(submit_url, headers=headers, json=body, timeout=request_timeout)
    except requests.exceptions.RequestException as e:
        raise _request_error("Replicate submit failed", e) from e
    prediction = _json_response(resp, "Replicate submit", api_key)
    pid = str(prediction.get("id") or "")
    if not _ID_RE.match(pid):
        raise ReplicateError("Replicate submit: missing or invalid prediction id")
    poll_url = _poll_url(base, prediction, pid)

    wait_budget = timeout if wait_seconds is None else wait_seconds
    deadline = time.monotonic() + max(0, float(wait_budget))
    status = str(prediction.get("status") or "starting")
    # незнакомый нетерминальный статус считаем «ещё идёт» — оплаченный запуск не бросаем
    while status not in _TERMINAL:
        if time.monotonic() >= deadline:
            return {"status": "pending", "id": pid, "poll_url": poll_url}
        if poll_interval:
            time.sleep(poll_interval)
        try:
            resp = session.get(poll_url, headers=headers, timeout=request_timeout)
        except requests.exceptions.RequestException as e:
            raise _request_error("Replicate poll failed", e) from e
        prediction = _json_response(resp, "Replicate poll", api_key)
        status = str(prediction.get("status") or "")

    if status == "failed":
        error = _redact(prediction.get("error") or "unknown error", api_key)[:500]
        raise ReplicateError(f"Replicate prediction {pid} failed: {error}")
    if status == "canceled":
        raise ReplicateError(f"Replicate prediction {pid} was canceled")

    output = prediction.get("output")
    refs = _media.collect_url_media_refs(output)
    result = {"status": "completed", "id": pid, "output": output,
              "output_urls": [r["url"] for r in refs], "poll_url": poll_url,
              "metrics": prediction.get("metrics")}
    if out_dir is not None:
        result.update(_media.download_media_refs(refs, out_dir, session=session,
                                                 timeout=download_timeout, brand="replicate"))
    return result
