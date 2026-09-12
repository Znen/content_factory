from pathlib import Path

import pytest
import requests

from gf.backends import higgsfield

API = "https://api.higgsfield.ai"
MODEL = "higgsfield-ai/soul/v2/standard"
KEY_ID = "29cee98f-key-id"
KEY_SECRET = "8456c1df-key-secret"
AUTH = f"Key {KEY_ID}:{KEY_SECRET}"
RID = "d7e6c0f3-6699-4f6c-bb45-2ad7fd9158ff"
STATUS_URL = f"{API}/requests/{RID}/status"
PRESIGNED = "https://fnf-api-input-prod.s3.amazonaws.com/in/x.jpeg?X-Amz-Signature=deadbeef"


class _Resp:
    def __init__(self, status_code=200, payload=None, text="", content=b""):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.content = content

    def json(self):
        if self._payload is None:
            raise ValueError("bad json")
        return self._payload


def _status(status, **fields):
    """Ответ /requests/{id}/status: конверт + типизированные media-поля модели."""
    return {"status": status, "request_id": RID, "status_url": STATUS_URL,
            "cancel_url": f"{API}/requests/{RID}/cancel", **fields}


class _Session:
    """Fake-сессия: POST upload-url, PUT в presigned S3, POST submit, GET poll, GET скачивания."""

    def __init__(self, polls=None, submit=None, downloads=None):
        self.posts, self.gets, self.puts = [], [], []
        self._polls = list(polls or [])
        self._submit = submit if submit is not None else _status("queued")
        self._downloads = downloads or {}
        self._file_n = 0

    def post(self, url, **kw):
        self.posts.append((url, kw))
        if url.endswith("/files/generate-upload-url"):
            self._file_n += 1
            ct = (kw.get("json") or {}).get("content_type", "application/octet-stream")
            return _Resp(200, {
                "public_url": f"https://cdn.higgsfield.example/in/f{self._file_n}.jpeg",
                "upload_url": PRESIGNED, "content_type": ct,
                "upload_headers": {"Content-Type": ct, "x-amz-tagging": "retention=temporary"}})
        return _Resp(200, self._submit)

    def put(self, url, **kw):
        self.puts.append((url, kw))
        return _Resp(200)

    def get(self, url, **kw):
        self.gets.append((url, kw))
        if url.startswith(f"{API}/requests/"):
            return _Resp(200, self._polls.pop(0))
        return _Resp(200, content=self._downloads.get(url, b"DATA"))

    @property
    def submits(self):
        return [(u, kw) for u, kw in self.posts if not u.endswith("/files/generate-upload-url")]

    @property
    def uploads(self):
        return [(u, kw) for u, kw in self.posts if u.endswith("/files/generate-upload-url")]


def _run(model, input, session, **kw):
    kw.setdefault("timeout", 5)
    kw.setdefault("poll_interval", 0)
    return higgsfield.run(model, input, api_key_id=KEY_ID, api_key_secret=KEY_SECRET,
                          session=session, **kw)


# ── submit: плоское тело по пути модели ────────────────────────────────────

def test_submit_posts_input_flat_to_model_path_with_key_auth():
    s = _Session(polls=[_status("completed", images=[])])
    _run(MODEL, {"prompt": "x", "num_images": 2}, s)
    url, kw = s.submits[0]
    assert url == f"{API}/{MODEL}"
    assert kw["json"] == {"prompt": "x", "num_images": 2}    # input — само тело, без обёртки
    assert kw["headers"]["Authorization"] == AUTH
    assert kw["headers"]["Content-Type"] == "application/json"


@pytest.mark.parametrize("model", [
    "veo3.1", "nano-banana", "veo3.1/fast/first-last-frame-to-video",
    "bytedance/seedance/v1/lite/image-to-video", "kling-video/v2.5-turbo/pro/text-to-video",
    "higgsfield-ai/soul/standard",
])
def test_model_paths_of_any_depth_are_accepted(model):
    s = _Session(polls=[_status("completed", images=[])])
    _run(model, {"prompt": "x"}, s)
    assert s.submits[0][0] == f"{API}/{model}"


@pytest.mark.parametrize("model", [
    "", "   ", "/veo3.1", "veo3.1/", "a//b", "a/../b", "..", ".", "a/./b",
    "https://api.higgsfield.ai/veo3.1", "veo3.1?x=1", "a\\b", "-bad", "a b",
    "a/b/c/d/e/f/g/h/i", "veo3.1#frag", "requests/x/status",
])
def test_model_validation_rejects_injection(model):
    with pytest.raises(higgsfield.HiggsfieldError):
        higgsfield.validate_model(model)


def test_invalid_model_makes_no_network_call():
    s = _Session()
    with pytest.raises(higgsfield.HiggsfieldError):
        _run("a/../b", {"prompt": "x"}, s)
    assert s.posts == [] and s.gets == [] and s.puts == []


def test_non_dict_input_rejected_without_network():
    s = _Session()
    with pytest.raises(higgsfield.HiggsfieldError, match="JSON object"):
        _run(MODEL, ["not", "a", "dict"], s)
    assert s.posts == []


# ── poll → completed → скачивание ──────────────────────────────────────────

def test_run_polls_until_completed_and_downloads_images(tmp_path):
    out_url = "https://cdn.higgsfield.example/out/generated-image.jpg"
    s = _Session(polls=[_status("queued"), _status("in_progress"),
                        _status("completed", images=[{"url": out_url}])],
                 downloads={out_url: b"IMG"})
    out = _run(MODEL, {"prompt": "x"}, s, out_dir=tmp_path)
    assert out["status"] == "completed" and out["id"] == RID
    assert out["output"] == {"images": [{"url": out_url}]}
    assert out["output_urls"] == [out_url]
    assert Path(out["media"]["images"][0]).read_bytes() == b"IMG"
    polls = [g for g in s.gets if g[0] == STATUS_URL]
    assert len(polls) == 3
    assert polls[0][1]["headers"]["Authorization"] == AUTH
    download = [g for g in s.gets if g[0] == out_url][0]
    assert "Authorization" not in (download[1].get("headers") or {})   # CDN — без ключа


def test_video_output_goes_to_video_subdir(tmp_path):
    clip = "https://cdn.higgsfield.example/out/video.mp4"
    s = _Session(polls=[_status("completed", video={"url": clip})], downloads={clip: b"MP4"})
    out = _run("veo3.1", {"prompt": "x"}, s, out_dir=tmp_path)
    path = Path(out["media"]["video"][0])
    assert path.parent.name == "video" and path.read_bytes() == b"MP4"
    assert out["output"] == {"video": {"url": clip}}


def test_audio_output_collected(tmp_path):
    au = "https://cdn.higgsfield.example/out/audio.mp3"
    s = _Session(polls=[_status("completed", audio={"url": au}, audios=[{"url": au}])],
                 downloads={au: b"MP3"})
    out = _run("veo3.1", {"prompt": "x"}, s, out_dir=tmp_path)
    assert out["output_urls"] == [au]                                  # дедуп audio/audios
    assert Path(out["media"]["audio"][0]).parent.name == "video"


def test_envelope_urls_are_not_treated_as_output_media(tmp_path):
    s = _Session(polls=[_status("completed", images=[])])
    out = _run(MODEL, {"prompt": "x"}, s, out_dir=tmp_path)
    assert out["output"] == {"images": []}                             # конверт вырезан
    assert out["output_urls"] == []
    assert [g[0] for g in s.gets] == [STATUS_URL]                      # status_url не качаем


def test_download_failure_preserves_url(tmp_path):
    out_url = "https://cdn.higgsfield.example/out/img.jpg"

    class _BadDownload(_Session):
        def get(self, url, **kw):
            if url == out_url:
                self.gets.append((url, kw))
                return _Resp(500, text="nope")
            return super().get(url, **kw)

    s = _BadDownload(polls=[_status("completed", images=[{"url": out_url}])])
    out = _run(MODEL, {"prompt": "x"}, s, out_dir=tmp_path)
    assert out["media_urls"] == [out_url] and out["warnings"]


def test_timeout_returns_pending_without_polling():
    s = _Session()
    out = _run(MODEL, {"prompt": "x"}, s, timeout=0, wait_seconds=0)
    assert out == {"status": "pending", "id": RID, "poll_url": STATUS_URL}
    assert s.gets == []
    assert s.submits[0][1]["timeout"] > 0


def test_missing_status_url_falls_back_to_requests_path():
    s = _Session(submit={"status": "queued", "request_id": RID},
                 polls=[_status("completed", images=[])])
    _run(MODEL, {"prompt": "x"}, s)
    assert s.gets[0][0] == STATUS_URL


def test_cross_origin_status_url_rejected_before_authorized_get():
    s = _Session(submit=_status("queued", status_url=f"https://evil.example/requests/{RID}/status"))
    with pytest.raises(higgsfield.HiggsfieldError, match="cross-origin"):
        _run(MODEL, {"prompt": "x"}, s)
    assert s.gets == []


def test_missing_request_id_rejected():
    s = _Session(submit={"status": "queued"})
    with pytest.raises(higgsfield.HiggsfieldError, match="request id"):
        _run(MODEL, {"prompt": "x"}, s)


def test_unknown_non_terminal_status_keeps_polling():
    s = _Session(polls=[_status("warming_up"), _status("completed", images=[])])
    out = _run(MODEL, {"prompt": "x"}, s)
    assert out["status"] == "completed"


# ── терминальные отказы и ошибки транспорта ────────────────────────────────

def test_failed_request_raises_with_api_error_text():
    s = _Session(polls=[_status("failed", error="Generation failed")])
    with pytest.raises(higgsfield.HiggsfieldError, match="Generation failed"):
        _run(MODEL, {"prompt": "x"}, s)


def test_nsfw_request_raises():
    s = _Session(polls=[_status("nsfw")])
    with pytest.raises(higgsfield.HiggsfieldError, match="nsfw"):
        _run(MODEL, {"prompt": "x"}, s)


def test_canceled_request_raises():
    s = _Session(polls=[_status("canceled")])
    with pytest.raises(higgsfield.HiggsfieldError, match="canceled"):
        _run(MODEL, {"prompt": "x"}, s)


@pytest.mark.parametrize("leak", [KEY_ID, KEY_SECRET, AUTH])
def test_terminal_error_text_never_contains_credentials(leak):
    s = _Session(polls=[_status("failed", error=f"bad auth {leak}")])
    with pytest.raises(higgsfield.HiggsfieldError) as e:
        _run(MODEL, {"prompt": "x"}, s)
    assert KEY_ID not in str(e.value) and KEY_SECRET not in str(e.value)


def test_http_error_includes_status_and_detail_but_not_credentials():
    class _Bad:
        def post(self, url, **kw):
            return _Resp(403, {"detail": f"Insufficient credits ({KEY_SECRET})"})

    with pytest.raises(higgsfield.HiggsfieldError) as e:
        _run(MODEL, {"prompt": "x"}, _Bad())
    msg = str(e.value)
    assert "HTTP 403" in msg and "Insufficient credits" in msg
    assert KEY_SECRET not in msg


def test_http_error_with_list_detail_is_readable():
    """422 отдаёт detail СПИСКОМ (FastAPI validation), не строкой — не падаем на этом."""
    class _Bad:
        def post(self, url, **kw):
            return _Resp(422, {"detail": [{"type": "missing", "loc": ["body", "prompt"],
                                           "msg": "Field required"}]})

    with pytest.raises(higgsfield.HiggsfieldError) as e:
        _run(MODEL, {}, _Bad())
    assert "HTTP 422" in str(e.value) and "Field required" in str(e.value)


def test_network_error_reports_type_name_without_credentials():
    class _Down:
        def post(self, url, **kw):
            raise requests.exceptions.ConnectionError(f"refused, header Key {KEY_ID}:{KEY_SECRET}")

    with pytest.raises(higgsfield.HiggsfieldError) as e:
        _run(MODEL, {"prompt": "x"}, _Down())
    msg = str(e.value)
    assert "ConnectionError" in msg and KEY_ID not in msg and KEY_SECRET not in msg


@pytest.mark.parametrize("kid,secret", [(None, KEY_SECRET), (KEY_ID, None), ("", ""),
                                        ("  ", KEY_SECRET), (KEY_ID, "  ")])
def test_missing_credentials_is_clean_error_without_network(kid, secret):
    s = _Session()
    with pytest.raises(higgsfield.HiggsfieldError,
                       match="HIGGSFIELD_API_KEY_ID/SECRET"):
        higgsfield.run(MODEL, {"prompt": "x"}, api_key_id=kid, api_key_secret=secret, session=s)
    assert s.posts == []


# ── presigned upload: @-маркеры → public_url ───────────────────────────────

def test_upload_file_two_step_presigned_contract(tmp_path):
    img = tmp_path / "Кадр 01.jpg"
    img.write_bytes(b"JPG")
    s = _Session()
    url = higgsfield.upload_file(img, api_key_id=KEY_ID, api_key_secret=KEY_SECRET,
                                 timeout=600, session=s)
    assert url == "https://cdn.higgsfield.example/in/f1.jpeg"

    post_url, post_kw = s.uploads[0]
    assert post_url == f"{API}/files/generate-upload-url"
    assert post_kw["json"] == {"content_type": "image/jpeg"}
    assert post_kw["headers"]["Authorization"] == AUTH

    put_url, put_kw = s.puts[0]
    assert put_url == PRESIGNED
    assert put_kw["data"] == b"JPG"
    assert put_kw["headers"] == {"Content-Type": "image/jpeg",
                                 "x-amz-tagging": "retention=temporary"}
    assert put_kw["timeout"] == 600                          # крупный файл не клампим до 30с


def test_upload_put_never_carries_higgsfield_credentials(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"P")
    s = _Session()
    higgsfield.upload_file(img, api_key_id=KEY_ID, api_key_secret=KEY_SECRET, session=s)
    headers = s.puts[0][1]["headers"]
    assert "Authorization" not in headers
    assert KEY_SECRET not in str(headers) and KEY_ID not in str(headers)


def test_upload_rejects_non_https_presigned_url(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"P")

    class _Plain(_Session):
        def post(self, url, **kw):
            self.posts.append((url, kw))
            return _Resp(200, {"public_url": "https://cdn/x.png",
                               "upload_url": "http://storage.example/x", "upload_headers": {}})

    s = _Plain()
    with pytest.raises(higgsfield.HiggsfieldError, match="https"):
        higgsfield.upload_file(img, api_key_id=KEY_ID, api_key_secret=KEY_SECRET, session=s)
    assert s.puts == []


def test_upload_failed_put_is_clean_error(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"P")

    class _BadPut(_Session):
        def put(self, url, **kw):
            self.puts.append((url, kw))
            return _Resp(403, text=f"denied {KEY_SECRET}")

    with pytest.raises(higgsfield.HiggsfieldError) as e:
        higgsfield.upload_file(img, api_key_id=KEY_ID, api_key_secret=KEY_SECRET, session=_BadPut())
    assert "HTTP 403" in str(e.value) and KEY_SECRET not in str(e.value)


def test_upload_missing_public_url_is_error(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"P")

    class _NoPub(_Session):
        def post(self, url, **kw):
            self.posts.append((url, kw))
            return _Resp(200, {"upload_url": PRESIGNED, "upload_headers": {}})

    with pytest.raises(higgsfield.HiggsfieldError, match="public_url"):
        higgsfield.upload_file(img, api_key_id=KEY_ID, api_key_secret=KEY_SECRET, session=_NoPub())


@pytest.mark.parametrize("name", ["nope.png", "a.unknownext"])
def test_upload_rejects_missing_or_untyped(tmp_path, name):
    if name.endswith("unknownext"):
        (tmp_path / name).write_bytes(b"X")
    s = _Session()
    with pytest.raises(higgsfield.HiggsfieldError):
        higgsfield.upload_file(tmp_path / name, api_key_id=KEY_ID, api_key_secret=KEY_SECRET,
                               session=s)
    assert s.posts == []


def test_upload_rejects_relative_path():
    with pytest.raises(higgsfield.HiggsfieldError, match="absolute"):
        higgsfield.upload_file("rel/a.png", api_key_id=KEY_ID, api_key_secret=KEY_SECRET,
                               session=_Session())


def test_upload_http_error_on_generate_url_is_clean(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"X")

    class _Bad:
        def post(self, url, **kw):
            return _Resp(500, {"detail": f"boom {KEY_SECRET}"})

    with pytest.raises(higgsfield.HiggsfieldError) as e:
        higgsfield.upload_file(img, api_key_id=KEY_ID, api_key_secret=KEY_SECRET, session=_Bad())
    assert "HTTP 500" in str(e.value) and KEY_SECRET not in str(e.value)


def test_resolve_upload_markers_everywhere_and_copies(tmp_path):
    img = tmp_path / "face.png"
    img.write_bytes(b"P")
    clip = tmp_path / "move.mp4"
    clip.write_bytes(b"M")
    original = {"image_url": f"@{img}", "prompt": "plain @alice",
                "nested": {"refs": [f"@{clip}", "https://cdn.example/x.png"]}}
    s = _Session()
    out = higgsfield.resolve_upload_markers(original, api_key_id=KEY_ID,
                                            api_key_secret=KEY_SECRET, session=s)
    assert out["image_url"] == "https://cdn.higgsfield.example/in/f1.jpeg"
    assert out["nested"]["refs"] == ["https://cdn.higgsfield.example/in/f2.jpeg",
                                     "https://cdn.example/x.png"]
    assert out["prompt"] == "plain @alice"                    # не маркер — как есть
    assert original["image_url"] == f"@{img}"                 # вход не мутирован
    assert len(s.uploads) == 2


def test_run_uploads_markers_before_submit(tmp_path):
    img = tmp_path / "ref.jpg"
    img.write_bytes(b"J")
    s = _Session(polls=[_status("completed", images=[])])
    _run("bytedance/seedance/v1/lite/image-to-video", {"image_url": f"@{img}", "prompt": "x"}, s)
    assert s.posts[0][0] == f"{API}/files/generate-upload-url"          # сначала upload
    body = s.submits[0][1]["json"]
    assert body["image_url"] == "https://cdn.higgsfield.example/in/f1.jpeg"
    assert not body["image_url"].startswith(("data:", "@"))
