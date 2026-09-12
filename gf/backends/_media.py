"""Общие хелперы скачивания выходных media для тонких бэкендов-очередей (fal, replicate).

Бэкенд находит в своём output ссылки на media (refs), а этот модуль их скачивает:
картинки -> out_dir, видео/аудио -> out_dir/video/. Упавшее скачивание НЕ теряет
оплаченный результат — URL уходит в media_urls + warning. Исключения наружу не летят.
"""

from __future__ import annotations

import datetime as dt
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import requests

MEDIA_KEYS = {
    "images", "image", "image_url",
    "videos", "video", "video_url",
    "audios", "audio", "audio_url", "audio_file",
    "files", "file", "file_url", "url",
}
MEDIA_EXTS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".mp4", ".mov", ".webm", ".m4v", ".mp3", ".wav", ".m4a", ".aac", ".flac",
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


class _DownloadError(Exception):
    """Внутреннее: ловится в download_media_refs, наружу не выходит."""


def media_ext(content_type: str = "", file_name: str = "", url: str = "") -> str:
    if content_type:
        ext = mimetypes.guess_extension(content_type.split(";", 1)[0].strip().lower()) or ""
        if ext == ".jpe":
            ext = ".jpg"
        if ext in MEDIA_EXTS:
            return ext
    for source in (file_name, urlparse(url).path):
        suffix = Path(source).suffix.lower()
        if suffix in MEDIA_EXTS:
            return suffix
    return ".bin"


def media_kind(content_type: str = "", file_name: str = "", url: str = "") -> str:
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    if ct.startswith("image/"):
        return "images"
    if ct.startswith("video/"):
        return "video"
    if ct.startswith("audio/"):
        return "audio"
    ext = media_ext(content_type, file_name, url)
    if ext in IMAGE_EXTS:
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


def _safe_name(brand: str, kind: str, index: int, *, url: str, content_type: str = "",
               file_name: str = "") -> str:
    ext = media_ext(content_type, file_name, url)
    stem = _sanitize_stem(file_name) if file_name else ""
    if not stem:
        parsed_stem = Path(urlparse(url).path).stem
        stem = _sanitize_stem(parsed_stem) if parsed_stem else ""
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = stem or f"{brand}_{kind}_{stamp}_{index:02d}"
    return f"{base}{ext}"


def is_http_url(value) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _media_ref_from_object(obj: dict, *, allow_unknown_ext: bool = False) -> "dict | None":
    url = obj.get("url") or obj.get("image_url") or obj.get("video_url") or obj.get("audio_url")
    if not is_http_url(url):
        return None
    content_type = str(obj.get("content_type") or obj.get("mime_type") or "")
    file_name = str(obj.get("file_name") or obj.get("filename") or obj.get("name") or "")
    if (not content_type and not allow_unknown_ext
            and media_ext(file_name=file_name, url=str(url)) == ".bin"):
        return None
    return {"url": url, "content_type": content_type, "file_name": file_name}


def string_media_ref(url: str) -> "dict | None":
    """http(s)-URL с media-расширением -> ref; всё прочее (текст, не-media URL) -> None."""
    if not is_http_url(url):
        return None
    if media_ext(url=url) == ".bin":
        return None
    return {"url": url, "content_type": mimetypes.guess_type(urlparse(url).path)[0] or "",
            "file_name": ""}


def url_media_ref(url: str) -> "dict | None":
    """http(s)-URL -> ref БЕЗ требования расширения в пути.

    Presigned-ссылки S3/CDN (.../provider-outputs/<hash>/<uuid>?X-Amz-Signature=...) несут
    тип только в Content-Type ответа — расширения в пути у них нет. Тип здесь остаётся
    пустым и доопределяется при скачивании (см. download_media_refs)."""
    if not is_http_url(url):
        return None
    return {"url": url, "content_type": mimetypes.guess_type(urlparse(url).path)[0] or "",
            "file_name": ""}


def _dedupe(found: list) -> list:
    out, seen = [], set()
    for ref in found:
        if ref["url"] not in seen:
            seen.add(ref["url"])
            out.append(ref)
    return out


def collect_keyed_media_refs(obj, *, parent_key: str = "",
                             allow_unknown_ext: bool = False) -> list:
    """fal-семантика: media ищется под известными ключами (images/video/url/...) и в
    объектах с url+content_type/file_name.

    allow_unknown_ext=True — для бэкендов, чей output несёт ТОЛЬКО url (higgsfield:
    MediaOutput = {url}, additionalProperties:false), где расширения в ссылке может не
    быть. Ключи по-прежнему обязаны быть media-ключами, так что чужие URL не подхватываются."""
    ref_of = url_media_ref if allow_unknown_ext else string_media_ref
    found = []
    if isinstance(obj, dict):
        ref = _media_ref_from_object(obj, allow_unknown_ext=allow_unknown_ext)
        if ref and (parent_key in MEDIA_KEYS or obj.get("content_type") or obj.get("file_name")):
            found.append(ref)
        for k, v in obj.items():
            key = str(k).lower()
            if isinstance(v, str) and key in MEDIA_KEYS:
                ref = ref_of(v)
                if ref:
                    found.append(ref)
            else:
                found.extend(collect_keyed_media_refs(v, parent_key=key,
                                                      allow_unknown_ext=allow_unknown_ext))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(collect_keyed_media_refs(v, parent_key=parent_key,
                                                  allow_unknown_ext=allow_unknown_ext))
    elif isinstance(obj, str) and parent_key in MEDIA_KEYS:
        ref = ref_of(obj)
        if ref:
            found.append(ref)
    return _dedupe(found)


def collect_url_media_refs(obj) -> list:
    """Replicate-семантика: output — голый URL, список URL или dict с произвольными
    ключами, без типовой обвязки. Берём ЛЮБУЮ http(s)-строку на любой глубине — БЕЗ
    требования media-расширения: presigned-выходы Replicate приходят как
    .../provider-outputs/<hash>/<uuid>?X-Amz-Signature=... и тип несут только в
    Content-Type ответа (доопределяется при скачивании)."""
    found = []

    def _walk(o):
        if isinstance(o, dict):
            for v in o.values():
                _walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                _walk(v)
        elif isinstance(o, str):
            ref = url_media_ref(o)
            if ref:
                found.append(ref)

    _walk(obj)
    return _dedupe(found)


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
    raise _DownloadError(f"Cannot allocate output filename for {name!r}")


def response_content_type(resp) -> str:
    """Content-Type ответа; пусто, если заголовков нет (фейки в тестах, экзотические клиенты)."""
    headers = getattr(resp, "headers", None) or {}
    if not hasattr(headers, "get"):
        return ""
    return str(headers.get("Content-Type") or headers.get("content-type") or "")


def download_media_refs(refs: list, out_dir: "str | Path", *, session=None, timeout: int = 120,
                        brand: str = "media") -> dict:
    """Скачать refs без auth-заголовков. Возвращает {media, media_urls (упавшие), warnings}.

    Вид и расширение выбираются ПОСЛЕ ответа: если ни ref, ни URL, ни file_name тип не дают
    (presigned-ссылка без расширения), он берётся из Content-Type ответа — иначе результат
    лёг бы как .bin в files/ или вовсе не был бы распознан."""
    session = session or requests
    out_dir = Path(out_dir)
    media = {"images": [], "video": [], "audio": [], "files": []}
    media_urls, warnings = [], []
    counters = {"images": 0, "video": 0, "audio": 0, "files": 0}
    for ref in refs:
        url = ref["url"]
        content_type = ref.get("content_type", "")
        file_name = ref.get("file_name", "")
        try:
            resp = session.get(url, timeout=timeout)
            if resp.status_code != 200:
                raise _DownloadError(f"HTTP {resp.status_code}")
            if not content_type and media_ext(file_name=file_name, url=url) == ".bin":
                content_type = response_content_type(resp)
            kind = media_kind(content_type, file_name, url)
            counters[kind] += 1
            name = _safe_name(brand, kind, counters[kind], url=url, content_type=content_type,
                              file_name=file_name)
            dest_dir = out_dir / _media_subdir(kind) if _media_subdir(kind) else out_dir
            path = _next_available(dest_dir, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(resp.content)
            media[kind].append(str(path))
        except (requests.exceptions.RequestException, _DownloadError, OSError) as e:
            media_urls.append(url)
            warnings.append(f"Failed to download {brand} output media; retained URL: {e}")
    return {"media": media, "media_urls": media_urls, "warnings": warnings}
