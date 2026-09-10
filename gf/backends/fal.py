"""fal.ai backend — thin async queue client with safe local media handling.

Contract:
- auth header: Authorization: Key <FAL_KEY>
- submit: POST https://queue.fal.run/{endpoint_id}
- workflows use endpoint IDs beginning with ``workflows/`` and the same queue contract
- list authenticated workflows: GET https://api.fal.ai/v1/workflows
- storage upload (fields that need real URLs): POST https://rest.fal.ai/storage/upload/initiate
  then PUT the bytes to the returned presigned upload_url (no Authorization on the PUT).
  The path carries no /api prefix: /api/storage/... answers 404, /storage/... answers 401
  without a key (verified live 2026).

The module deliberately exposes one public exception, ``FalError``. Messages never include
the API key.
"""

from __future__ import annotations

import base64
import datetime as dt
import mimetypes
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests


DEFAULT_QUEUE_URL = "https://queue.fal.run"
DEFAULT_API_URL = "https://api.fal.ai"
DEFAULT_STORAGE_URL = "https://rest.fal.ai"
DEFAULT_TIMEOUT = 180
DEFAULT_POLL_INTERVAL = 3
DEFAULT_DOWNLOAD_TIMEOUT = 120

_ENDPOINT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_WINDOWS_FILE_MARKER_RE = re.compile(r"^@[A-Za-z]:[\\/]")
_MEDIA_KEYS = {
    "images", "image", "image_url",
    "videos", "video", "video_url",
    "audios", "audio", "audio_url", "audio_file",
    "files", "file", "file_url", "url",
}
_MEDIA_EXTS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".mp4", ".mov", ".webm", ".m4v", ".mp3", ".wav", ".m4a", ".aac", ".flac",
}
# Поля, в которых fal требует НАСТОЯЩИЕ HTTP-URL (data URI отклоняется), например
# bytedance/seedance-2.0/reference-to-video — локальный файл идёт через fal storage.
_UPLOAD_URL_KEYS = {"video_urls", "image_urls", "audio_urls"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_VIDEO_AUDIO_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".mp3", ".wav", ".m4a", ".aac", ".flac"}


class FalError(Exception):
    pass


def validate_endpoint_id(endpoint_id: str) -> str:
    endpoint_id = (endpoint_id or "").strip()
    parsed = urlparse(endpoint_id)
    if (
        not endpoint_id
        or parsed.scheme
        or parsed.netloc
        or endpoint_id.startswith(("/", "\\"))
        or "\\" in endpoint_id
        or "//" in endpoint_id
        or ".." in endpoint_id.split("/")
        or not _ENDPOINT_RE.match(endpoint_id)
    ):
        raise FalError(f"Invalid fal endpoint_id: {endpoint_id!r}")
    return endpoint_id


def _headers(api_key: str | None) -> dict:
    if not api_key:
        raise FalError("Missing FAL_KEY. Set FAL_KEY in .env to use fal.ai.")
    return {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}


def _request_timeout(timeout: int) -> int:
    return max(1, min(int(timeout or DEFAULT_TIMEOUT), 30))


def _upload_timeout(timeout: int) -> int:
    """Full timeout, deliberately NOT clamped like _request_timeout: an uploaded file
    can be large and a 30s cap would abort a healthy transfer."""
    return max(1, int(timeout or DEFAULT_TIMEOUT))


def _request_error(prefix: str, exc: Exception) -> FalError:
    return FalError(f"{prefix}: {type(exc).__name__}")


def _json_response(resp, context: str) -> dict:
    if resp.status_code >= 400:
        raise FalError(f"{context}: HTTP {resp.status_code}")
    try:
        obj = resp.json()
    except ValueError as e:
        raise FalError(f"{context}: invalid JSON response") from e
    if not isinstance(obj, dict):
        raise FalError(f"{context}: expected JSON object response")
    return obj


def _mime_for_path(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        raise FalError(f"Cannot determine MIME type for local file: {path}")
    return mime


def _marker_path(value: str) -> Path:
    """``@C:/path/file`` marker -> validated local Path."""
    p = Path(value[1:] if value.startswith("@") else value)
    if not p.is_absolute():
        raise FalError(f"Local file marker must use an absolute path: {value}")
    if not p.exists() or not p.is_file():
        raise FalError(f"Local file marker not found: {p}")
    return p


def encode_file_marker(value: str) -> str:
    """Convert explicit Windows ``@C:/path/file`` markers; other ``@...`` strings stay plain."""
    if not isinstance(value, str) or not _WINDOWS_FILE_MARKER_RE.match(value):
        return value
    p = _marker_path(value)
    mime = _mime_for_path(p)
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode('ascii')}"


def encode_local_file_markers(obj):
    """Recursively convert explicit local file markers inside fal input payloads."""
    if isinstance(obj, dict):
        return {k: encode_local_file_markers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [encode_local_file_markers(v) for v in obj]
    if isinstance(obj, tuple):
        return [encode_local_file_markers(v) for v in obj]
    if isinstance(obj, str):
        return encode_file_marker(obj)
    return obj


def upload_file(local_path: "str | Path", *, api_key: str | None,
                api_url: str = DEFAULT_STORAGE_URL, timeout: int = DEFAULT_TIMEOUT,
                session=None) -> str:
    """Upload a local file to fal storage; return its public ``file_url``.

    Two steps per the storage contract: ``POST {api_url}/storage/upload/initiate``
    (authorized) hands back a presigned ``upload_url`` plus the final ``file_url``, then the
    raw bytes go to ``upload_url`` with ``PUT`` and **no** Authorization header (presigned).
    """
    session = session or requests
    p = Path(local_path)
    if not p.is_absolute():
        raise FalError(f"Upload path must be absolute: {local_path}")
    if not p.exists() or not p.is_file():
        raise FalError(f"Upload file not found: {p}")
    content_type = _mime_for_path(p)
    request_timeout = _upload_timeout(timeout)
    try:
        resp = session.post(f"{api_url.rstrip('/')}/storage/upload/initiate",
                            headers=_headers(api_key),
                            json={"content_type": content_type, "file_name": p.name},
                            timeout=request_timeout)
    except requests.exceptions.RequestException as e:
        raise _request_error("fal upload initiate failed", e) from e
    data = _json_response(resp, "fal upload initiate")
    upload_url, file_url = data.get("upload_url"), data.get("file_url")
    if not upload_url or not file_url:
        raise FalError("fal upload initiate: missing upload_url/file_url in response")
    try:
        payload = p.read_bytes()
    except OSError as e:
        raise FalError(f"Cannot read upload file {p}: {type(e).__name__}") from e
    try:
        put = session.put(upload_url, data=payload,
                          headers={"Content-Type": content_type},   # presigned: no auth header
                          timeout=request_timeout)
    except requests.exceptions.RequestException as e:
        raise _request_error("fal upload failed", e) from e
    if put.status_code != 200:
        raise FalError(f"fal upload: HTTP {put.status_code}")
    return str(file_url)


def resolve_upload_markers(input: dict, *, api_key: str | None,
                           api_url: str = DEFAULT_STORAGE_URL, timeout: int = DEFAULT_TIMEOUT,
                           session=None) -> dict:
    """Local file markers inside ``video_urls``/``image_urls``/``audio_urls`` -> fal storage URLs.

    Those fields demand real HTTP URLs, so a data URI is not an option there; every other
    value (including markers elsewhere, e.g. in ``prompt``) is returned untouched for
    ``encode_local_file_markers``. The input is copied, never mutated in place.
    """
    def _walk(obj, parent_key: str = ""):
        if isinstance(obj, dict):
            return {k: _walk(v, str(k).lower()) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_walk(v, parent_key) for v in obj]
        if (isinstance(obj, str) and parent_key in _UPLOAD_URL_KEYS
                and _WINDOWS_FILE_MARKER_RE.match(obj)):
            return upload_file(_marker_path(obj), api_key=api_key, api_url=api_url,
                               timeout=timeout, session=session)
        return obj

    return _walk(input)


def _norm_status(status: str) -> str:
    status = (status or "").upper()
    if status == "COMPLETED":
        return "COMPLETED"
    if status == "FAILED":
        return "FAILED"
    if status == "IN_PROGRESS":
        return "IN_PROGRESS"
    if status == "IN_QUEUE":
        return "IN_QUEUE"
    if status:
        raise FalError(f"fal queue returned unknown status {status!r}")
    return "IN_QUEUE"


def _effective_port(parsed) -> int:
    try:
        port = parsed.port
    except ValueError as e:
        raise FalError("fal URL has invalid port") from e
    if port is not None:
        return port
    return 443 if parsed.scheme == "https" else 80


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise FalError("fal queue URL must be absolute http(s)")
    return parsed.scheme, parsed.hostname.lower(), _effective_port(parsed)


def _validate_queue_url(queue_url: str) -> str:
    _origin(queue_url)
    return queue_url.rstrip("/")


def _queue_url(queue_url: str, url: str | None, context: str) -> str:
    if not url:
        raise FalError(f"{context}: missing URL")
    base = _validate_queue_url(queue_url)
    absolute = url if url.startswith(("http://", "https://")) else urljoin(f"{base}/", url.lstrip("/"))
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise FalError(f"{context}: invalid queue URL")
    if _origin(absolute) != _origin(base):
        raise FalError(f"{context}: cross-origin queue URL rejected")
    return absolute


def _media_ext(content_type: str = "", file_name: str = "", url: str = "") -> str:
    if content_type:
        ext = mimetypes.guess_extension(content_type.split(";", 1)[0].strip().lower()) or ""
        if ext == ".jpe":
            ext = ".jpg"
        if ext in _MEDIA_EXTS:
            return ext
    for source in (file_name, urlparse(url).path):
        suffix = Path(source).suffix.lower()
        if suffix in _MEDIA_EXTS:
            return suffix
    return ".bin"


def _media_kind(content_type: str = "", file_name: str = "", url: str = "") -> str:
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    if ct.startswith("image/"):
        return "images"
    if ct.startswith("video/"):
        return "video"
    if ct.startswith("audio/"):
        return "audio"
    ext = _media_ext(content_type, file_name, url)
    if ext in _IMAGE_EXTS:
        return "images"
    if ext in {".mp4", ".mov", ".webm", ".m4v"}:
        return "video"
    if ext in {".mp3", ".wav", ".m4a", ".aac", ".flac"}:
        return "audio"
    return "files"


def _sanitize_stem(value: str) -> str:
    stem = Path(value or "").stem
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)
    return safe[:80] or "output"


def _safe_name(prefix: str, index: int, *, url: str, content_type: str = "",
               file_name: str = "") -> str:
    ext = _media_ext(content_type, file_name, url)
    stem = _sanitize_stem(file_name) if file_name else ""
    if not stem:
        parsed_stem = Path(urlparse(url).path).stem
        stem = _sanitize_stem(parsed_stem) if parsed_stem else ""
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = stem or f"fal_{prefix}_{stamp}_{index:02d}"
    return f"{base}{ext}"


def _is_http_url(value: str) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _media_ref_from_object(obj: dict) -> dict | None:
    url = obj.get("url") or obj.get("image_url") or obj.get("video_url") or obj.get("audio_url")
    if not _is_http_url(url):
        return None
    content_type = str(obj.get("content_type") or obj.get("mime_type") or "")
    file_name = str(obj.get("file_name") or obj.get("filename") or obj.get("name") or "")
    if not content_type and _media_ext(file_name, url=url) == ".bin":
        return None
    return {"url": url, "content_type": content_type, "file_name": file_name}


def _string_media_ref(url: str) -> dict | None:
    if not _is_http_url(url):
        return None
    ext = _media_ext(url=url)
    if ext == ".bin":
        return None
    return {"url": url, "content_type": mimetypes.guess_type(urlparse(url).path)[0] or "",
            "file_name": ""}


def _collect_media_refs(obj, *, parent_key: str = "") -> list[dict]:
    found = []
    if isinstance(obj, dict):
        ref = _media_ref_from_object(obj)
        if ref and (parent_key in _MEDIA_KEYS or obj.get("content_type") or obj.get("file_name")):
            found.append(ref)
        for k, v in obj.items():
            key = str(k).lower()
            if isinstance(v, str) and key in _MEDIA_KEYS:
                ref = _string_media_ref(v)
                if ref:
                    found.append(ref)
            else:
                found.extend(_collect_media_refs(v, parent_key=key))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(_collect_media_refs(v, parent_key=parent_key))
    elif isinstance(obj, str) and parent_key in _MEDIA_KEYS:
        ref = _string_media_ref(obj)
        if ref:
            found.append(ref)
    out = []
    seen = set()
    for ref in found:
        url = ref["url"]
        if url not in seen:
            seen.add(url)
            out.append(ref)
    return out


def _media_subdir(kind: str) -> str:
    return "video" if kind in {"video", "audio"} else ""


def _next_available(dest_dir: Path, name: str) -> Path:
    path = dest_dir / name
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(2, 10_000):
        candidate = dest_dir / f"{stem}-{i:02d}{suffix}"
        if not candidate.exists():
            return candidate
    raise FalError(f"Cannot allocate output filename for {name!r}")


def download_output_media(output: dict, out_dir: str | Path, *, session=None,
                          timeout: int = DEFAULT_DOWNLOAD_TIMEOUT) -> dict:
    """Download common fal output media URLs, preserving failed URLs plus warnings."""
    session = session or requests
    out_dir = Path(out_dir)
    refs = _collect_media_refs(output)
    media = {"images": [], "video": [], "audio": [], "files": []}
    media_urls = []
    warnings = []
    counters = {"images": 0, "video": 0, "audio": 0, "files": 0}
    for ref in refs:
        url = ref["url"]
        kind = _media_kind(ref.get("content_type", ""), ref.get("file_name", ""), url)
        dest_dir = out_dir / _media_subdir(kind) if _media_subdir(kind) else out_dir
        counters[kind] += 1
        name = _safe_name(kind, counters[kind], url=url,
                          content_type=ref.get("content_type", ""),
                          file_name=ref.get("file_name", ""))
        path = _next_available(dest_dir, name)
        try:
            resp = session.get(url, timeout=timeout)
            if resp.status_code != 200:
                raise FalError(f"HTTP {resp.status_code}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(resp.content)
            media[kind].append(str(path))
        except (requests.exceptions.RequestException, FalError) as e:
            media_urls.append(url)
            warnings.append(f"Failed to download fal output media; retained URL: {e}")
    return {"media": media, "media_urls": media_urls, "warnings": warnings}


def list_workflows(*, api_key: str | None, api_url: str = DEFAULT_API_URL,
                   limit: int = 50, cursor: str = "", search: str = "",
                   used_endpoint_ids: str = "", session=None,
                   timeout: int = DEFAULT_TIMEOUT) -> dict:
    session = session or requests
    try:
        limit = int(limit)
    except (TypeError, ValueError) as e:
        raise FalError("fal list_workflows: limit must be a positive integer") from e
    if limit <= 0:
        raise FalError("fal list_workflows: limit must be a positive integer")
    params = {"limit": limit}
    request_timeout = _request_timeout(timeout)
    if cursor:
        params["cursor"] = cursor
    if search:
        params["search"] = search
    if used_endpoint_ids:
        params["used_endpoint_ids"] = used_endpoint_ids
    try:
        resp = session.get(f"{api_url.rstrip('/')}/v1/workflows",
                           headers=_headers(api_key), params=params, timeout=request_timeout)
    except requests.exceptions.RequestException as e:
        raise _request_error("fal list_workflows failed", e) from e
    data = _json_response(resp, "fal list_workflows")
    if "workflows" not in data or not isinstance(data.get("workflows"), list):
        raise FalError("fal list_workflows: missing workflows[] in response")
    return data


def run(endpoint_id: str, input: dict, *, api_key: str | None,
        queue_url: str = DEFAULT_QUEUE_URL, timeout: int = DEFAULT_TIMEOUT,
        wait_seconds: "int | float | None" = None,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        download_timeout: int = DEFAULT_DOWNLOAD_TIMEOUT,
        out_dir: str | Path | None = None, session=None) -> dict:
    if not isinstance(input, dict):
        raise FalError("fal input must be a JSON object")
    endpoint_id = validate_endpoint_id(endpoint_id)
    queue_base = _validate_queue_url(queue_url)
    session = session or requests
    submit_url = f"{queue_base}/{endpoint_id}"
    headers = _headers(api_key)
    request_timeout = _request_timeout(timeout)
    # порядок важен: url-поля сначала уходят в fal storage (там нужен HTTP-URL),
    # и только потом ОСТАВШИЕСЯ @-маркеры (например в prompt) становятся data-URI
    input = resolve_upload_markers(input, api_key=api_key, timeout=timeout, session=session)
    body = encode_local_file_markers(input)
    try:
        resp = session.post(submit_url, headers=headers, json=body, timeout=request_timeout)
    except requests.exceptions.RequestException as e:
        raise _request_error("fal submit failed", e) from e
    submitted = _json_response(resp, "fal submit")
    request_id = submitted.get("request_id")
    if not request_id:
        raise FalError("fal submit: missing request_id in response")
    status_url = _queue_url(queue_base, submitted.get("status_url"), "fal submit status_url")
    response_url = _queue_url(queue_base, submitted.get("response_url"), "fal submit response_url")

    wait_budget = timeout if wait_seconds is None else wait_seconds
    deadline = time.monotonic() + max(0, float(wait_budget))
    status = _norm_status(submitted.get("status", "IN_QUEUE"))
    latest = submitted
    while status in {"IN_QUEUE", "IN_PROGRESS"}:
        if time.monotonic() >= deadline:
            return {"status": "pending", "request_id": request_id, "status_url": status_url,
                    "response_url": response_url}
        if poll_interval:
            time.sleep(poll_interval)
        try:
            resp = session.get(status_url, headers=headers, timeout=request_timeout)
        except requests.exceptions.RequestException as e:
            raise _request_error("fal status poll failed", e) from e
        latest = _json_response(resp, "fal status poll")
        status = _norm_status(str(latest.get("status") or ""))
        request_id = latest.get("request_id") or request_id
        if latest.get("status_url"):
            status_url = _queue_url(queue_base, latest.get("status_url"), "fal poll status_url")
        if latest.get("response_url"):
            response_url = _queue_url(queue_base, latest.get("response_url"), "fal poll response_url")

    if status == "FAILED":
        raise FalError(f"fal request {request_id} failed")

    try:
        resp = session.get(response_url, headers=headers, timeout=request_timeout)
    except requests.exceptions.RequestException as e:
        raise _request_error("fal response fetch failed", e) from e
    output = _json_response(resp, "fal response fetch")
    result = {"status": "completed", "request_id": request_id, "output": output,
              "status_url": status_url, "response_url": response_url}
    if out_dir is not None:
        result.update(download_output_media(output, out_dir, session=session,
                                            timeout=download_timeout))
    return result
