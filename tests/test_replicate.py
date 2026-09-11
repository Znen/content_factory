from pathlib import Path

import pytest
import requests

from gf.backends import replicate

API = "https://api.replicate.com"
VERSION = "5c7d5dc6dd8bf75c1acaa8565735e7986bc5b66206b55cca93cb72c9bf15ccaa"
POLL_URL = f"{API}/v1/predictions/p1"
TOKEN = "r8_secret_token"


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


def _prediction(status, output=None, error=None, get=POLL_URL):
    return {"id": "p1", "status": status, "output": output, "error": error,
            "urls": {"get": get, "cancel": f"{get}/cancel"}}


class _Session:
    """Fake-сессия: различает POST /v1/files, POST submit, GET poll и GET скачивания."""

    def __init__(self, polls=None, submit=None, downloads=None):
        self.posts, self.gets = [], []
        self._polls = list(polls or [])
        self._submit = submit or _prediction("starting")
        self._downloads = downloads or {}
        self._file_n = 0

    def post(self, url, **kw):
        self.posts.append((url, kw))
        if url.endswith("/v1/files"):
            self._file_n += 1
            return _Resp(201, {"id": f"f{self._file_n}",
                               "urls": {"get": f"{API}/v1/files/f{self._file_n}"}})
        return _Resp(201, self._submit)

    def get(self, url, **kw):
        self.gets.append((url, kw))
        if url.startswith(f"{API}/v1/predictions/"):
            return _Resp(200, self._polls.pop(0))
        return _Resp(200, content=self._downloads.get(url, b"DATA"))

    @property
    def submits(self):
        return [(u, kw) for u, kw in self.posts if not u.endswith("/v1/files")]

    @property
    def uploads(self):
        return [(u, kw) for u, kw in self.posts if u.endswith("/v1/files")]


def _run(model, input, session, **kw):
    kw.setdefault("timeout", 5)
    kw.setdefault("poll_interval", 0)
    return replicate.run(model, input, api_key=TOKEN, session=session, **kw)


# ── submit: два пути по формату model ──────────────────────────────────────

def test_version_hash_submits_to_predictions_with_version():
    s = _Session(polls=[_prediction("succeeded", output="ok")])
    _run(VERSION, {"prompt": "x"}, s)
    url, kw = s.submits[0]
    assert url == f"{API}/v1/predictions"
    assert kw["json"] == {"version": VERSION, "input": {"prompt": "x"}}
    assert kw["headers"]["Authorization"] == f"Bearer {TOKEN}"


def test_owner_name_submits_to_model_predictions_without_version():
    s = _Session(polls=[_prediction("succeeded", output="ok")])
    _run("black-forest-labs/flux-schnell", {"prompt": "x"}, s)
    url, kw = s.submits[0]
    assert url == f"{API}/v1/models/black-forest-labs/flux-schnell/predictions"
    assert kw["json"] == {"input": {"prompt": "x"}}


def test_owner_name_with_version_goes_to_predictions_with_hash():
    s = _Session(polls=[_prediction("succeeded", output="ok")])
    _run(f"stability-ai/sdxl:{VERSION}", {"prompt": "x"}, s)
    url, kw = s.submits[0]
    assert url == f"{API}/v1/predictions"
    assert kw["json"]["version"] == VERSION


@pytest.mark.parametrize("model", [
    "", "https://api.replicate.com/v1/models/a/b", "/owner/name", "owner/../x",
    "owner//name", "owner\\name", "a/b/c", "justname", "owner/name:nothex",
    "z" * 64, "owner/name?x=1",
])
def test_model_validation_rejects_injection(model):
    with pytest.raises(replicate.ReplicateError):
        replicate.validate_model(model)


def test_invalid_model_makes_no_network_call():
    s = _Session()
    with pytest.raises(replicate.ReplicateError):
        _run("owner/../x", {"prompt": "x"}, s)
    assert s.posts == [] and s.gets == []


# ── poll → succeeded → скачивание ──────────────────────────────────────────

def test_run_polls_until_succeeded_and_downloads_images(tmp_path):
    out_url = "https://replicate.delivery/pbxt/abc/out-0.png"
    s = _Session(polls=[_prediction("processing"), _prediction("succeeded", output=[out_url])],
                 downloads={out_url: b"IMG"})
    out = _run(VERSION, {"prompt": "x"}, s, out_dir=tmp_path)
    assert out["status"] == "completed" and out["id"] == "p1"
    assert out["output"] == [out_url]
    assert out["output_urls"] == [out_url]
    assert Path(out["media"]["images"][0]).read_bytes() == b"IMG"
    poll_gets = [g for g in s.gets if g[0] == POLL_URL]
    assert len(poll_gets) == 2
    assert poll_gets[0][1]["headers"]["Authorization"] == f"Bearer {TOKEN}"
    download = [g for g in s.gets if g[0] == out_url][0]
    assert "Authorization" not in (download[1].get("headers") or {})   # CDN — без токена


def test_video_output_string_goes_to_video_subdir(tmp_path):
    clip = "https://replicate.delivery/xezq/clip.mp4"
    s = _Session(polls=[_prediction("succeeded", output=clip)], downloads={clip: b"MP4"})
    out = _run("kwaivgi/kling-v2.1", {"prompt": "x"}, s, out_dir=tmp_path)
    path = Path(out["media"]["video"][0])
    assert path.parent.name == "video" and path.read_bytes() == b"MP4"


def test_text_output_returned_without_media(tmp_path):
    s = _Session(polls=[_prediction("succeeded", output=["Hello", " world"])])
    out = _run("meta/llama", {"prompt": "hi"}, s, out_dir=tmp_path)
    assert out["output"] == ["Hello", " world"]
    assert out["output_urls"] == []
    assert out["media"] == {"images": [], "video": [], "audio": [], "files": []}


def test_download_failure_preserves_url(tmp_path):
    out_url = "https://replicate.delivery/pbxt/abc/out-0.png"

    class _BadDownload(_Session):
        def get(self, url, **kw):
            if url == out_url:
                self.gets.append((url, kw))
                return _Resp(500, text="nope")
            return super().get(url, **kw)

    s = _BadDownload(polls=[_prediction("succeeded", output=[out_url])])
    out = _run(VERSION, {"prompt": "x"}, s, out_dir=tmp_path)
    assert out["media_urls"] == [out_url] and out["warnings"]


def test_timeout_returns_pending_without_polling():
    s = _Session()
    out = _run(VERSION, {"prompt": "x"}, s, timeout=0, wait_seconds=0)
    assert out == {"status": "pending", "id": "p1", "poll_url": POLL_URL}
    assert s.gets == []
    assert s.submits[0][1]["timeout"] > 0


def test_missing_poll_url_falls_back_to_prediction_path():
    submit = {"id": "p1", "status": "starting", "urls": {}}
    s = _Session(submit=submit, polls=[_prediction("succeeded", output="ok")])
    _run(VERSION, {"prompt": "x"}, s)
    assert s.gets[0][0] == POLL_URL


def test_cross_origin_poll_url_rejected_before_authorized_get():
    s = _Session(submit=_prediction("starting", get="https://evil.example/v1/predictions/p1"))
    with pytest.raises(replicate.ReplicateError, match="cross-origin"):
        _run(VERSION, {"prompt": "x"}, s)
    assert s.gets == []


# ── ошибки: failed/canceled, HTTP, сеть, токен ─────────────────────────────

def test_failed_prediction_raises_with_api_error_text():
    s = _Session(polls=[_prediction("failed", error="CUDA out of memory")])
    with pytest.raises(replicate.ReplicateError, match="CUDA out of memory"):
        _run(VERSION, {"prompt": "x"}, s)


def test_canceled_prediction_raises():
    s = _Session(polls=[_prediction("canceled")])
    with pytest.raises(replicate.ReplicateError, match="canceled"):
        _run(VERSION, {"prompt": "x"}, s)


def test_prediction_error_text_never_contains_token():
    s = _Session(polls=[_prediction("failed", error=f"bad auth {TOKEN}")])
    with pytest.raises(replicate.ReplicateError) as e:
        _run(VERSION, {"prompt": "x"}, s)
    assert TOKEN not in str(e.value)


def test_http_error_includes_status_and_detail_but_not_token():
    class _Bad:
        def post(self, url, **kw):
            return _Resp(422, {"detail": f"input.prompt is required ({TOKEN})"})

    with pytest.raises(replicate.ReplicateError) as e:
        _run(VERSION, {}, _Bad())
    msg = str(e.value)
    assert "HTTP 422" in msg and "input.prompt is required" in msg
    assert TOKEN not in msg


def test_network_error_reports_type_name_without_token():
    class _Down:
        def post(self, url, **kw):
            raise requests.exceptions.ConnectionError(f"refused, header Bearer {TOKEN}")

    with pytest.raises(replicate.ReplicateError) as e:
        _run(VERSION, {"prompt": "x"}, _Down())
    assert "ConnectionError" in str(e.value)
    assert TOKEN not in str(e.value)


def test_missing_token_is_clean_error_without_network():
    s = _Session()
    with pytest.raises(replicate.ReplicateError, match="REPLICATE_API_TOKEN"):
        replicate.run(VERSION, {"prompt": "x"}, api_key=None, session=s)
    assert s.posts == []


# ── Files API: @-маркеры → загрузка → URL ──────────────────────────────────

def test_upload_file_multipart_contract_and_full_timeout(tmp_path):
    img = tmp_path / "Кадр 01.png"
    img.write_bytes(b"PNG")
    s = _Session()
    url = replicate.upload_file(img, api_key=TOKEN, timeout=600, session=s)
    assert url == f"{API}/v1/files/f1"
    post_url, kw = s.uploads[0]
    assert post_url == f"{API}/v1/files"
    assert kw["files"]["content"] == ("Кадр 01.png", b"PNG", "image/png")
    assert kw["data"]["filename"] == "Кадр 01.png"
    assert kw["headers"] == {"Authorization": f"Bearer {TOKEN}"}   # без json Content-Type
    assert kw["timeout"] == 600                                     # НЕ клампится до 30с


@pytest.mark.parametrize("name", ["nope.png", "a.unknownext"])
def test_upload_file_rejects_missing_or_untyped(tmp_path, name):
    if name.endswith("unknownext"):
        (tmp_path / name).write_bytes(b"X")
    s = _Session()
    with pytest.raises(replicate.ReplicateError):
        replicate.upload_file(tmp_path / name, api_key=TOKEN, session=s)
    assert s.posts == []


def test_upload_file_rejects_relative_path():
    with pytest.raises(replicate.ReplicateError, match="absolute"):
        replicate.upload_file("rel/a.png", api_key=TOKEN, session=_Session())


def test_upload_file_http_error_is_clean(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"X")

    class _Bad:
        def post(self, url, **kw):
            return _Resp(500, {"detail": f"boom {TOKEN}"})

    with pytest.raises(replicate.ReplicateError) as e:
        replicate.upload_file(img, api_key=TOKEN, session=_Bad())
    assert "HTTP 500" in str(e.value) and TOKEN not in str(e.value)


def test_resolve_upload_markers_everywhere_and_copies(tmp_path):
    img = tmp_path / "face.png"
    img.write_bytes(b"P")
    clip = tmp_path / "move.mp4"
    clip.write_bytes(b"M")
    original = {"image": f"@{img}", "prompt": "plain @alice",
                "nested": {"refs": [f"@{clip}", "https://cdn.example/x.png"]}}
    s = _Session()
    out = replicate.resolve_upload_markers(original, api_key=TOKEN, session=s)
    assert out["image"] == f"{API}/v1/files/f1"
    assert out["nested"]["refs"] == [f"{API}/v1/files/f2", "https://cdn.example/x.png"]
    assert out["prompt"] == "plain @alice"                       # не маркер — как есть
    assert original["image"] == f"@{img}"                         # вход не мутирован
    assert len(s.uploads) == 2


def test_run_uploads_markers_before_submit(tmp_path):
    img = tmp_path / "ref.jpg"
    img.write_bytes(b"J")
    s = _Session(polls=[_prediction("succeeded", output="ok")])
    _run("owner/model", {"image": f"@{img}", "prompt": "x"}, s)
    assert s.posts[0][0] == f"{API}/v1/files"                     # сначала upload
    body = s.submits[0][1]["json"]["input"]
    assert body["image"] == f"{API}/v1/files/f1"                  # Files-URL, не data-URI/маркер
    assert not body["image"].startswith(("data:", "@"))
