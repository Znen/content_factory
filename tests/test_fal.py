import base64
from pathlib import Path

import pytest

from gf.backends import fal


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


class _Session:
    def __init__(self):
        self.posts = []
        self.gets = []
        self._get = []

    def queue_get(self, resp):
        self._get.append(resp)

    def post(self, url, **kw):
        self.posts.append((url, kw))
        return _Resp(payload={"request_id": "rid-1", "status_url": "https://queue.fal.run/status/rid-1",
                              "response_url": "https://queue.fal.run/result/rid-1"})

    def get(self, url, **kw):
        self.gets.append((url, kw))
        return self._get.pop(0)


@pytest.mark.parametrize("endpoint", [
    "https://queue.fal.run/fal-ai/x", "/fal-ai/x", "fal-ai/../x", "fal-ai//x",
    "fal-ai\\x",
])
def test_endpoint_validation_rejects_injection(endpoint):
    with pytest.raises(fal.FalError):
        fal.validate_endpoint_id(endpoint)


def test_endpoint_validation_accepts_models_and_workflows():
    assert fal.validate_endpoint_id("fal-ai/nano-banana-pro") == "fal-ai/nano-banana-pro"
    assert fal.validate_endpoint_id("workflows/my-workflow") == "workflows/my-workflow"


def test_local_file_marker_encodes_data_uri(tmp_path):
    img = tmp_path / "in.png"
    img.write_bytes(b"PNG")
    out = fal.encode_local_file_markers({"image": f"@{img}", "prompt": "plain @text"})
    assert out["prompt"] == "plain @text"
    assert out["image"].startswith("data:image/png;base64,")
    assert out["image"].split(",", 1)[1] == base64.b64encode(b"PNG").decode("ascii")


def test_at_prefixed_prompt_is_not_local_file_marker():
    out = fal.encode_local_file_markers({"prompt": "@alice portrait", "tag": "@brand"})
    assert out == {"prompt": "@alice portrait", "tag": "@brand"}


def test_windows_backslash_file_marker_encodes_data_uri(tmp_path):
    img = tmp_path / "ref.jpg"
    img.write_bytes(b"JPEG")
    marker = "@" + str(img)
    assert "\\" in marker
    out = fal.encode_file_marker(marker)
    assert out.startswith("data:image/jpeg;base64,")
    assert out.split(",", 1)[1] == base64.b64encode(b"JPEG").decode("ascii")


def test_run_submit_poll_result_and_downloads_media(tmp_path):
    s = _Session()
    s.queue_get(_Resp(payload={"status": "IN_PROGRESS"}))
    s.queue_get(_Resp(payload={"status": "COMPLETED"}))
    s.queue_get(_Resp(payload={"images": [{"url": "https://cdn.fal.ai/out.png"}]}))
    s.queue_get(_Resp(content=b"IMG"))
    out = fal.run("fal-ai/nano-banana-pro", {"prompt": "x"}, api_key="fk",
                  timeout=2, poll_interval=0, out_dir=tmp_path, session=s)
    assert out["status"] == "completed"
    assert out["request_id"] == "rid-1"
    assert out["output"]["images"][0]["url"] == "https://cdn.fal.ai/out.png"
    assert len(out["media"]["images"]) == 1
    assert Path(out["media"]["images"][0]).read_bytes() == b"IMG"
    assert s.posts[0][1]["headers"]["Authorization"] == "Key fk"


def test_status_normalization_is_official_and_explicit():
    assert fal._norm_status("IN_QUEUE") == "IN_QUEUE"
    assert fal._norm_status("IN_PROGRESS") == "IN_PROGRESS"
    assert fal._norm_status("COMPLETED") == "COMPLETED"
    with pytest.raises(fal.FalError):
        fal._norm_status("QUEUED")


def test_run_timeout_returns_pending():
    s = _Session()
    out = fal.run("fal-ai/nano-banana-pro", {"prompt": "x"}, api_key="fk",
                  timeout=0, wait_seconds=0, poll_interval=0, session=s)
    assert out == {"status": "pending", "request_id": "rid-1",
                   "status_url": "https://queue.fal.run/status/rid-1",
                   "response_url": "https://queue.fal.run/result/rid-1"}
    assert s.posts[0][1]["timeout"] > 0


def test_run_missing_key_is_clean_error():
    with pytest.raises(fal.FalError, match="FAL_KEY"):
        fal.run("fal-ai/nano-banana-pro", {"prompt": "x"}, api_key=None)


def test_workflow_listing():
    class _WorkflowSession:
        def __init__(self):
            self.calls = []

        def get(self, url, **kw):
            self.calls.append((url, kw))
            return _Resp(payload={"workflows": [{"endpoint_id": "workflows/a"}],
                                  "next_cursor": "c2", "has_more": True, "total": 2})

    s = _WorkflowSession()
    out = fal.list_workflows(api_key="fk", search="cat", used_endpoint_ids="fal-ai/x",
                             limit=10, cursor="c1", session=s)
    assert out["workflows"][0]["endpoint_id"] == "workflows/a"
    assert s.calls[0][1]["params"] == {"limit": 10, "cursor": "c1", "search": "cat",
                                       "used_endpoint_ids": "fal-ai/x"}


@pytest.mark.parametrize("limit", [0, -1, "x"])
def test_workflow_listing_validates_limit(limit):
    with pytest.raises(fal.FalError, match="positive integer"):
        fal.list_workflows(api_key="fk", limit=limit)


def test_cross_origin_queue_urls_are_rejected_before_authorized_get():
    class _EvilSession(_Session):
        def post(self, url, **kw):
            self.posts.append((url, kw))
            return _Resp(payload={"request_id": "rid-1",
                                  "status": "IN_QUEUE",
                                  "status_url": "https://evil.example/status/rid-1",
                                  "response_url": "https://queue.fal.run/result/rid-1"})

    s = _EvilSession()
    with pytest.raises(fal.FalError, match="cross-origin"):
        fal.run("fal-ai/nano-banana-pro", {"prompt": "x"}, api_key="fk", session=s)
    assert s.gets == []


def test_http_errors_do_not_include_raw_body():
    class _BadSession:
        def post(self, url, **kw):
            return _Resp(status_code=500, text="echoed FAL_KEY=fk-secret")

    with pytest.raises(fal.FalError) as e:
        fal.run("fal-ai/nano-banana-pro", {"prompt": "x"}, api_key="fk", session=_BadSession())
    assert "HTTP 500" in str(e.value)
    assert "fk-secret" not in str(e.value)


def test_extensionless_media_objects_use_content_type_and_file_name(tmp_path):
    class _Downloads:
        def __init__(self):
            self.calls = []
            self.payloads = [b"V", b"A"]

        def get(self, url, **kw):
            self.calls.append((url, kw))
            return _Resp(content=self.payloads.pop(0))

    out = fal.download_output_media({
        "videos": [{"url": "https://cdn.fal.ai/result", "content_type": "video/mp4",
                    "file_name": "clip"}],
        "audio_file": {"url": "https://cdn.fal.ai/audio", "content_type": "audio/mpeg",
                       "file_name": "voice"},
        "image": {"url": "https://cdn.fal.ai/result", "content_type": "video/mp4",
                  "file_name": "duplicate"},
    }, tmp_path, session=_Downloads())
    assert len(out["media"]["video"]) == 1
    assert len(out["media"]["audio"]) == 1
    assert Path(out["media"]["video"][0]).name == "clip.mp4"
    assert Path(out["media"]["audio"][0]).parent.name == "video"
    assert Path(out["media"]["video"][0]).read_bytes() == b"V"


def test_download_failure_preserves_url(tmp_path):
    class _BadDownload:
        def get(self, url, **kw):
            return _Resp(status_code=500, text="nope")

    out = fal.download_output_media({"video": {"url": "https://cdn.fal.ai/clip.mp4"}},
                                    tmp_path, session=_BadDownload())
    assert out["media_urls"] == ["https://cdn.fal.ai/clip.mp4"]
    assert out["warnings"]
    assert not list(tmp_path.rglob("*.mp4"))


# ── fal storage upload (video_urls/image_urls/audio_urls ждут HTTP-URL, не data-URI) ──

INITIATE_URL = "https://rest.fal.ai/storage/upload/initiate"
PRESIGNED_URL = "https://upload.fal.media/presigned/abc"
FILE_URL = "https://v3.fal.media/files/abc/f.mp4"


class _UploadSession(_Session):
    """Fake-сессия, различающая initiate-POST, presigned-PUT и submit-POST."""

    def __init__(self, initiate=None):
        super().__init__()
        self.puts = []
        self._initiate = initiate if initiate is not None else {
            "upload_url": PRESIGNED_URL, "file_url": FILE_URL}

    def post(self, url, **kw):
        if url.endswith("/storage/upload/initiate"):
            self.posts.append((url, kw))
            return _Resp(payload=self._initiate)
        return super().post(url, **kw)

    def put(self, url, **kw):
        self.puts.append((url, kw))
        return _Resp()


def test_run_uploads_local_files_in_url_array_fields(tmp_path):
    clip = tmp_path / "shot.mp4"
    clip.write_bytes(b"MP4")
    s = _UploadSession()
    s.queue_get(_Resp(payload={"status": "COMPLETED"}))
    s.queue_get(_Resp(payload={"video": {"url": "https://cdn.fal.ai/out.mp4"}}))
    s.queue_get(_Resp(content=b"OUT"))

    out = fal.run("bytedance/seedance-2.0/reference-to-video",
                  {"video_urls": [f"@{clip}"], "prompt": "x"}, api_key="fk",
                  timeout=2, poll_interval=0, out_dir=tmp_path, session=s)

    assert out["status"] == "completed"
    initiate_url, initiate_kw = s.posts[0]
    assert initiate_url == INITIATE_URL
    assert initiate_kw["json"] == {"content_type": "video/mp4", "file_name": "shot.mp4"}
    assert initiate_kw["headers"]["Authorization"] == "Key fk"
    assert s.puts[0][0] == PRESIGNED_URL
    assert s.puts[0][1]["data"] == b"MP4"
    assert s.puts[0][1]["headers"] == {"Content-Type": "video/mp4"}
    submit_body = s.posts[1][1]["json"]
    assert submit_body["video_urls"] == [FILE_URL]     # fal-URL, НЕ data:base64
    assert submit_body["prompt"] == "x"


def test_run_keeps_data_uri_for_markers_outside_url_fields(tmp_path):
    img = tmp_path / "ref.png"
    img.write_bytes(b"PNG")
    s = _UploadSession()

    out = fal.run("fal-ai/nano-banana-pro", {"prompt": f"@{img}"}, api_key="fk",
                  timeout=0, wait_seconds=0, poll_interval=0, session=s)

    assert out["status"] == "pending"
    assert s.puts == []                                 # upload не вызывался
    assert s.posts[0][0].endswith("fal-ai/nano-banana-pro")   # первый POST = submit
    assert s.posts[0][1]["json"]["prompt"].startswith("data:image/png;base64,")


def test_upload_file_returns_file_url_and_uses_full_timeout(tmp_path):
    clip = tmp_path / "ИФЛ_002.mp4"
    clip.write_bytes(b"BYTES")
    s = _UploadSession()

    url = fal.upload_file(clip, api_key="fk", timeout=600, session=s)

    assert url == FILE_URL
    assert s.posts[0][1]["json"] == {"content_type": "video/mp4", "file_name": "ИФЛ_002.mp4"}
    assert s.posts[0][1]["timeout"] == 600              # НЕ клампится до 30с
    assert s.puts[0][1]["timeout"] == 600
    assert "Authorization" not in s.puts[0][1]["headers"]   # presigned PUT — без ключа


def test_upload_file_initiate_failure_is_clean_error(tmp_path):
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"X")

    class _BadInitiate:
        def post(self, url, **kw):
            return _Resp(status_code=500, text="echoed Key fk-secret")

    with pytest.raises(fal.FalError) as e:
        fal.upload_file(clip, api_key="fk-secret", session=_BadInitiate())
    assert "HTTP 500" in str(e.value)
    assert "fk-secret" not in str(e.value)


def test_upload_file_put_failure_is_error(tmp_path):
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"X")

    class _BadPut(_UploadSession):
        def put(self, url, **kw):
            self.puts.append((url, kw))
            return _Resp(status_code=403, text="denied fk-secret")

    with pytest.raises(fal.FalError) as e:
        fal.upload_file(clip, api_key="fk-secret", session=_BadPut())
    assert "fk-secret" not in str(e.value)


def test_upload_file_requires_file_url_in_initiate_response(tmp_path):
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"X")
    s = _UploadSession(initiate={"upload_url": PRESIGNED_URL})
    with pytest.raises(fal.FalError):
        fal.upload_file(clip, api_key="fk", session=s)
    assert s.puts == []


def test_upload_file_rejects_unknown_mime(tmp_path):
    weird = tmp_path / "a.unknownext"
    weird.write_bytes(b"X")
    s = _UploadSession()
    with pytest.raises(fal.FalError, match="MIME"):
        fal.upload_file(weird, api_key="fk", session=s)
    assert s.posts == []


def test_upload_file_rejects_missing_file(tmp_path):
    with pytest.raises(fal.FalError):
        fal.upload_file(tmp_path / "nope.mp4", api_key="fk", session=_UploadSession())


def test_resolve_upload_markers_touches_only_url_fields_and_copies(tmp_path):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"M")
    s = _UploadSession()
    original = {"video_urls": [f"@{clip}"], "image_urls": ["https://cdn.example/x.png"],
                "audio_urls": [f"@{clip}"], "prompt": f"@{clip}"}

    out = fal.resolve_upload_markers(original, api_key="fk", session=s)

    assert original["video_urls"] == [f"@{clip}"]        # вход не мутирован
    assert out["video_urls"] == [FILE_URL]
    assert out["audio_urls"] == [FILE_URL]
    assert out["image_urls"] == ["https://cdn.example/x.png"]   # не маркер — как есть
    assert out["prompt"] == f"@{clip}"                   # не url-поле — не аплоадится
