"""Nano Banana backend — thin HTTP client for the external Nitro Express server.

Ported from Q:/Lion Films. AI studio/tools/nitro_banana/nitro_generate.py, stripped
of all tools.common / budget / workspace coupling. Pure HTTP: cost-gating and project
layout live in the caller. No seed support (server doesn't accept one).
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import time
from pathlib import Path

import requests

DEFAULT_TIMEOUT = 120
TOKEN_TTL_S = 7 * 24 * 60 * 60
DEFAULT_TOKEN_CACHE = Path.home() / ".lionfilms" / "nitro_banana_token.json"
VALID_ASPECTS = {"16:9", "1:1", "3:4", "4:3", "9:16"}
MAX_REFS = 4
SUPPORTED_INPUT_MIMES = {
    ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".webp": "image/webp",
}


class NanoError(Exception):
    pass


class AuthExpired(Exception):
    pass


def encode_inputs(paths: list[Path]) -> tuple[list[str], list[str]]:
    b64s, mimes = [], []
    for p in paths:
        p = Path(p)
        if not p.exists():
            raise FileNotFoundError(f"Input file not found: {p}")
        mime = SUPPORTED_INPUT_MIMES.get(p.suffix.lower())
        if not mime:
            raise ValueError(
                f"Unsupported input type: {p.name} (supported: {sorted(SUPPORTED_INPUT_MIMES)})")
        b64s.append(base64.b64encode(p.read_bytes()).decode("ascii"))
        mimes.append(mime)
    return b64s, mimes


def save_image(image_url_data: str, out_path: Path) -> int:
    b64 = image_url_data.split(",", 1)[1] if image_url_data.startswith("data:") else image_url_data
    raw = base64.b64decode(b64)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(raw)
    return len(raw)


def _get_cached_token(cache_path: Path) -> "str | None":
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if data.get("expires_at", 0) > time.time() + 60:
            return data.get("token")
    except (json.JSONDecodeError, OSError):
        return None
    return None


def _cache_token(cache_path: Path, token: str) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"token": token, "expires_at": time.time() + TOKEN_TTL_S}),
        encoding="utf-8")


def _login(session, server_url: str, password: str) -> str:
    url = f"{server_url.rstrip('/')}/api/auth/login"
    try:
        r = session.post(url, json={"password": password}, timeout=10)
    except requests.exceptions.ConnectionError as e:
        raise NanoError(f"Cannot reach Nitro server at {server_url}. "
                        f"Start it: `cd R:\\nitro_banana && npm run dev:server`. ({e})") from e
    if r.status_code == 401:
        raise NanoError("Login failed: invalid NITRO_BANANA_APP_PASSWORD.")
    if r.status_code != 200:
        raise NanoError(f"Login failed: HTTP {r.status_code} {r.text[:200]}")
    token = r.json().get("token")
    if not token:
        raise NanoError(f"Login response missing token: {r.text[:200]}")
    return token


def _get_token(session, server_url, password, cache_path, force=False) -> str:
    if not force:
        cached = _get_cached_token(cache_path)
        if cached:
            return cached
    if not password:
        raise NanoError("No cached token and no password (NITRO_BANANA_APP_PASSWORD).")
    token = _login(session, server_url, password)
    _cache_token(cache_path, token)
    return token


def _call_gemini(session, server_url: str, token: str, payload: dict, timeout: int) -> dict:
    url = f"{server_url.rstrip('/')}/api/gemini"
    headers = {"Authorization": f"Bearer {token}", "X-App-Auth": f"Bearer {token}",
               "Content-Type": "application/json"}
    try:
        r = session.post(url, headers=headers, json=payload, timeout=timeout)
    except requests.exceptions.ConnectionError as e:
        raise NanoError(f"Cannot reach Nitro server at {server_url}. ({e})") from e
    except requests.exceptions.Timeout as e:
        raise NanoError(f"Request timed out after {timeout}s ({e})") from e
    if r.status_code == 401:
        raise AuthExpired("token rejected")
    if r.status_code == 429:
        raise NanoError("QUOTA_EXCEEDED — Gemini quota exhausted, retry later.")
    if r.status_code != 200:
        raise NanoError(f"HTTP {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except json.JSONDecodeError:
        raise NanoError(f"Non-JSON response: {r.text[:200]}")


def generate(prompt: str, refs: "list[Path]", out_dir: Path, *,
             server_url: str, password: "str | None", timeout: int = DEFAULT_TIMEOUT,
             aspect: str = "9:16", token_cache: "Path | None" = None, session=None) -> "list[Path]":
    """Edit-generate one final image with up to 4 base64 refs. Returns saved paths."""
    if aspect not in VALID_ASPECTS:
        raise NanoError(f"Invalid aspect {aspect!r} (valid: {sorted(VALID_ASPECTS)})")
    refs = [Path(r) for r in (refs or [])]
    if len(refs) > MAX_REFS:
        raise NanoError(f"Nano accepts at most {MAX_REFS} reference images, got {len(refs)}")
    session = session or requests
    token_cache = token_cache or DEFAULT_TOKEN_CACHE

    b64s, mimes = encode_inputs(refs) if refs else ([], [])
    payload = {"action": "edit", "base64Datas": b64s, "mimeTypes": mimes,
               "prompt": prompt or "", "aspectRatio": aspect, "imageSize": "1K"}

    token = _get_token(session, server_url, password, token_cache)
    try:
        resp = _call_gemini(session, server_url, token, payload, timeout)
    except AuthExpired:
        token = _get_token(session, server_url, password, token_cache, force=True)
        resp = _call_gemini(session, server_url, token, payload, timeout)

    image = resp.get("imageUrl")
    if not image:
        raise NanoError(f"Response missing imageUrl: {json.dumps(resp)[:200]}")
    out_dir = Path(out_dir)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"nano_{stamp}.png"
    save_image(image, out_path)
    return [out_path]
