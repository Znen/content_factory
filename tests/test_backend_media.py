"""Общий слой скачивания media (gf/backends/_media.py).

Ключевой случай: presigned-URL БЕЗ расширения в пути (S3/CDN, тип — в Content-Type
ответа). Раньше такая ссылка не считалась media и результат генерации терялся.
"""

from pathlib import Path

import pytest

from gf.backends import _media

NO_EXT = ("https://replicate.delivery/xezq/provider-outputs/9c1f/"
          "3f2a8b10-5d6e-4c7a-9b8f-1e2d3c4b5a60?X-Amz-Signature=abc")
WITH_EXT = "https://cdn.example/out/frame.png"


class _Resp:
    def __init__(self, status_code=200, content=b"", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


class _Downloader:
    def __init__(self, mapping):
        self.mapping = mapping
        self.gets = []

    def get(self, url, **kw):
        self.gets.append((url, kw))
        content, ctype = self.mapping[url]
        return _Resp(200, content, {"Content-Type": ctype} if ctype else {})


# ── url-семантика (replicate): расширение необязательно ────────────────────

def test_collect_url_media_refs_accepts_extensionless_url():
    refs = _media.collect_url_media_refs([NO_EXT])
    assert [r["url"] for r in refs] == [NO_EXT]
    assert refs[0]["content_type"] == ""          # тип пока неизвестен — придёт при скачивании


def test_collect_url_media_refs_still_types_urls_with_extension():
    refs = _media.collect_url_media_refs({"out": WITH_EXT})
    assert refs[0]["content_type"] == "image/png"


def test_collect_url_media_refs_ignores_non_urls_and_dedupes():
    refs = _media.collect_url_media_refs(["Hello", "not a url", NO_EXT, NO_EXT])
    assert [r["url"] for r in refs] == [NO_EXT]


# ── keyed-семантика (fal) не изменилась ────────────────────────────────────

def test_string_media_ref_unchanged_still_requires_extension():
    assert _media.string_media_ref(NO_EXT) is None
    assert _media.string_media_ref(WITH_EXT)["content_type"] == "image/png"


def test_collect_keyed_media_refs_default_still_skips_extensionless():
    assert _media.collect_keyed_media_refs({"images": [{"url": NO_EXT}]}) == []
    assert _media.collect_keyed_media_refs({"images": [NO_EXT]}) == []


def test_collect_keyed_media_refs_opt_in_accepts_extensionless():
    """higgsfield: MediaOutput несёт ТОЛЬКО url (additionalProperties:false)."""
    refs = _media.collect_keyed_media_refs({"images": [{"url": NO_EXT}]},
                                           allow_unknown_ext=True)
    assert [r["url"] for r in refs] == [NO_EXT]
    refs = _media.collect_keyed_media_refs({"video": {"url": NO_EXT}}, allow_unknown_ext=True)
    assert [r["url"] for r in refs] == [NO_EXT]


def test_collect_keyed_media_refs_opt_in_still_ignores_non_media_keys():
    out = {"seed": 123, "meta": {"docs": "https://docs.example/page"}}
    assert _media.collect_keyed_media_refs(out, allow_unknown_ext=True) == []


# ── скачивание: тип и расширение из Content-Type ───────────────────────────

@pytest.mark.parametrize("ctype,suffix,kind,subdir", [
    ("image/jpeg", ".jpg", "images", ""),
    ("image/png", ".png", "images", ""),
    ("video/mp4", ".mp4", "video", "video"),
    ("audio/mpeg", ".mp3", "audio", "video"),
])
def test_download_uses_response_content_type_when_url_has_no_extension(
        tmp_path, ctype, suffix, kind, subdir):
    s = _Downloader({NO_EXT: (b"BYTES", ctype)})
    res = _media.download_media_refs([{"url": NO_EXT, "content_type": "", "file_name": ""}],
                                     tmp_path, session=s, brand="replicate")
    path = Path(res["media"][kind][0])
    assert path.suffix == suffix
    assert path.read_bytes() == b"BYTES"
    assert path.parent.name == (subdir or tmp_path.name)
    assert res["media_urls"] == [] and res["warnings"] == []


def test_download_prefers_known_content_type_over_response_header(tmp_path):
    s = _Downloader({WITH_EXT: (b"P", "application/octet-stream")})
    res = _media.download_media_refs(
        [{"url": WITH_EXT, "content_type": "image/png", "file_name": ""}],
        tmp_path, session=s, brand="fal")
    assert Path(res["media"]["images"][0]).suffix == ".png"


def test_download_falls_back_to_files_when_type_unknown_everywhere(tmp_path):
    s = _Downloader({NO_EXT: (b"X", "")})
    res = _media.download_media_refs([{"url": NO_EXT, "content_type": "", "file_name": ""}],
                                     tmp_path, session=s, brand="replicate")
    assert Path(res["media"]["files"][0]).suffix == ".bin"


def test_download_tolerates_response_without_headers_attribute(tmp_path):
    class _NoHeaders:
        def get(self, url, **kw):
            r = _Resp(200, b"X")
            del r.headers
            return r

    res = _media.download_media_refs([{"url": NO_EXT, "content_type": "", "file_name": ""}],
                                     tmp_path, session=_NoHeaders(), brand="replicate")
    assert Path(res["media"]["files"][0]).exists()


def test_failed_download_still_retains_url_and_warns(tmp_path):
    class _Bad:
        def get(self, url, **kw):
            return _Resp(500)

    res = _media.download_media_refs([{"url": NO_EXT, "content_type": "", "file_name": ""}],
                                     tmp_path, session=_Bad(), brand="replicate")
    assert res["media_urls"] == [NO_EXT] and res["warnings"]
    assert res["media"] == {"images": [], "video": [], "audio": [], "files": []}
