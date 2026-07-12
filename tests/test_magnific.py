"""Тесты Magnific-бэкенда (Freepik REST). Инъецируемый session, без живых API.

Контракт подтверждён вживую 2026-07-09 (см. шапку gf/backends/magnific.py)."""
import base64
import json
from pathlib import Path

import pytest
import requests

from gf.backends import magnific


def _png(tmp_path, name="ref.png"):
    p = tmp_path / name
    p.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
    return p


# ── encode + _build_payload (per-model пути/поля) ─────────────────────────

def test_encode_ref_base64_roundtrip(tmp_path):
    p = _png(tmp_path)
    b64 = magnific.encode_ref(p)
    assert base64.b64decode(b64) == b"\x89PNG\r\n\x1a\nFAKE"


def test_encode_ref_rejects_unsupported(tmp_path):
    bad = tmp_path / "x.gif"
    bad.write_bytes(b"GIF")
    with pytest.raises(magnific.MagnificError):
        magnific.encode_ref(bad)


def test_build_payload_seedream_refs_array(tmp_path):
    ref = _png(tmp_path)
    path, body = magnific._build_payload("seedream-v4-5-edit", "make it cinematic",
                                         [ref], "widescreen_16_9")
    assert path == "/v1/ai/text-to-image/seedream-v4-5-edit"
    assert body["prompt"] == "make it cinematic"
    assert body["aspect_ratio"] == "widescreen_16_9"
    assert isinstance(body["reference_images"], list) and len(body["reference_images"]) == 1
    assert base64.b64decode(body["reference_images"][0]) == b"\x89PNG\r\n\x1a\nFAKE"


def test_build_payload_flux_single_input_image(tmp_path):
    ref = _png(tmp_path)
    path, body = magnific._build_payload("flux-kontext-pro", "edit this", [ref], "")
    assert path == "/v1/ai/text-to-image/flux-kontext-pro"
    assert "input_image" in body and isinstance(body["input_image"], str)
    assert "reference_images" not in body
    assert "aspect_ratio" not in body   # пустой aspect не передаётся


def test_build_payload_mystic_t2i_no_refs(tmp_path):
    path, body = magnific._build_payload("mystic", "a red fox in snow", [], "square_1_1")
    assert path == "/v1/ai/mystic"
    assert body["prompt"] == "a red fox in snow"
    assert "reference_images" not in body and "input_image" not in body


def test_build_payload_mystic_with_refs_raises(tmp_path):
    with pytest.raises(magnific.MagnificError) as e:
        magnific._build_payload("mystic", "x", [_png(tmp_path)], "")
    assert "seedream" in str(e.value).lower()


def test_build_payload_seedream_requires_at_least_one_ref(tmp_path):
    with pytest.raises(magnific.MagnificError):
        magnific._build_payload("seedream-v4-5-edit", "x", [], "")


def test_build_payload_seedream_too_many_refs(tmp_path):
    refs = [_png(tmp_path, f"r{i}.png") for i in range(6)]
    with pytest.raises(magnific.MagnificError):
        magnific._build_payload("seedream-v4-5-edit", "x", refs, "")


def test_build_payload_flux_requires_exactly_one_ref(tmp_path):
    with pytest.raises(magnific.MagnificError):
        magnific._build_payload("flux-kontext-pro", "x", [], "")
    with pytest.raises(magnific.MagnificError):
        magnific._build_payload("flux-kontext-pro", "x",
                                [_png(tmp_path, "a.png"), _png(tmp_path, "b.png")], "")


def test_build_payload_unknown_model_lists_known(tmp_path):
    with pytest.raises(magnific.MagnificError) as e:
        magnific._build_payload("bogus", "x", [], "")
    assert "mystic" in str(e.value)


def test_build_payload_nano_banana_pro_t2i_no_refs(tmp_path):
    # рефы опциональны (ref_min=0): 0 рефов = чистый t2i, поле reference_images НЕ добавляется
    path, body = magnific._build_payload("nano-banana-pro", "a red fox in snow", [], "9:16")
    assert path == "/v1/ai/text-to-image/nano-banana-pro"
    assert body["prompt"] == "a red fox in snow"
    assert body["aspect_ratio"] == "9:16"          # обычный формат, НЕ magnific-enum
    assert "reference_images" not in body          # пустое поле не шлём


def test_build_payload_nano_banana_pro_with_refs(tmp_path):
    refs = [_png(tmp_path, "a.png"), _png(tmp_path, "b.png")]
    path, body = magnific._build_payload("nano-banana-pro", "combine face and location", refs, "")
    assert path == "/v1/ai/text-to-image/nano-banana-pro"
    assert isinstance(body["reference_images"], list) and len(body["reference_images"]) == 2


def test_build_payload_nano_banana_pro_too_many_refs(tmp_path):
    refs = [_png(tmp_path, f"r{i}.png") for i in range(5)]   # max 4
    with pytest.raises(magnific.MagnificError):
        magnific._build_payload("nano-banana-pro", "x", refs, "")


# ── FIX: per-model формат элемента reference_images (объекты vs голые строки) ──
# nano-banana-pro ждёт reference_images как список ОБЪЕКТОВ {image, mime_type}
# (голые строки → 400 "Input should be a valid dictionary"); seedream — голые строки.

def test_build_payload_nano_banana_pro_refs_as_objects(tmp_path):
    ref = _png(tmp_path)
    path, body = magnific._build_payload("nano-banana-pro", "combine face and location", [ref], "")
    assert path == "/v1/ai/text-to-image/nano-banana-pro"
    imgs = body["reference_images"]
    assert isinstance(imgs, list) and len(imgs) == 1
    assert isinstance(imgs[0], dict)                       # объект, не голая строка
    assert base64.b64decode(imgs[0]["image"]) == b"\x89PNG\r\n\x1a\nFAKE"
    assert imgs[0]["mime_type"] == "image/png"


def test_build_payload_seedream_refs_stay_bare_strings(tmp_path):
    # регрессия: seedream по-прежнему шлёт голые base64-строки, НЕ объекты
    ref = _png(tmp_path)
    _, body = magnific._build_payload("seedream-v4-5-edit", "x", [ref], "")
    assert all(isinstance(x, str) for x in body["reference_images"])
    assert base64.b64decode(body["reference_images"][0]) == b"\x89PNG\r\n\x1a\nFAKE"


def test_build_payload_nano_banana_pro_mime_jpeg(tmp_path):
    ref = _png(tmp_path, "photo.jpg")                     # .jpg → image/jpeg
    _, body = magnific._build_payload("nano-banana-pro", "x", [ref], "")
    assert body["reference_images"][0]["mime_type"] == "image/jpeg"


def test_build_payload_nano_banana_pro_mime_webp(tmp_path):
    ref = _png(tmp_path, "sticker.webp")                  # .webp → image/webp
    _, body = magnific._build_payload("nano-banana-pro", "x", [ref], "")
    assert body["reference_images"][0]["mime_type"] == "image/webp"


# ── generate: POST → poll → download (инъецируемый session) ───────────────

_BASE = "https://api.magnific.com"


class _Resp:
    def __init__(self, status, payload=None, content=b""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = json.dumps(self._payload)
        self.content = content

    def json(self):
        return self._payload


class _FakeSession:
    """POST → CREATED+task_id; poll-GET проходит статусы; download-GET (не на base) → байты."""
    def __init__(self, poll_statuses=("IN_PROGRESS", "COMPLETED"),
                 generated=("https://cdn.freepik/img.png",), img=b"IMGDATA",
                 post_status=200, post_payload=None):
        self.calls = []
        self._statuses = list(poll_statuses)
        self._i = 0
        self._generated = list(generated)
        self._img = img
        self._post_status = post_status
        self._post_payload = post_payload

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        if self._post_status != 200:
            return _Resp(self._post_status, self._post_payload or {"message": "err"})
        return _Resp(200, {"data": {"task_id": "tid-1", "status": "CREATED", "generated": []}})

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        if not url.startswith(_BASE):          # download подписанного CDN-URL
            return _Resp(200, content=self._img)
        st = self._statuses[min(self._i, len(self._statuses) - 1)]
        self._i += 1
        data = {"task_id": "tid-1", "status": st}
        if st == "COMPLETED":
            data["generated"] = self._generated
        return _Resp(200, {"data": data})


def _gen(tmp_path, sess, model="seedream-v4-5-edit", refs=None, **kw):
    refs = refs if refs is not None else [_png(tmp_path)]
    return magnific.generate("cinematic portrait", refs, tmp_path / "out",
                             model=model, base_url=_BASE, api_key="mk-test",
                             session=sess, poll_interval=0, **kw)


def test_generate_happy_path_saves_and_maps(tmp_path):
    sess = _FakeSession()
    out = _gen(tmp_path, sess)
    assert out["timed_out"] is False
    assert out["task_id"] == "tid-1"
    assert len(out["images"]) == 1
    saved = Path(out["images"][0])
    assert saved.exists() and saved.read_bytes() == b"IMGDATA"
    assert saved.name.startswith("magnific_seedream-v4-5-edit_")
    # POST нёс ключ и base64-референс
    post = next(c for c in sess.calls if c[0] == "POST")
    assert post[2]["headers"]["x-magnific-api-key"] == "mk-test"
    assert len(post[2]["json"]["reference_images"]) == 1


def test_generate_polls_multiple_in_progress(tmp_path):
    sess = _FakeSession(poll_statuses=("IN_PROGRESS", "IN_PROGRESS", "IN_PROGRESS", "COMPLETED"))
    out = _gen(tmp_path, sess)
    assert out["timed_out"] is False and len(out["images"]) == 1
    polls = [c for c in sess.calls if c[0] == "GET" and c[1].startswith(_BASE)]
    assert len(polls) == 4


def test_generate_failed_raises(tmp_path):
    sess = _FakeSession(poll_statuses=("IN_PROGRESS", "FAILED"))
    with pytest.raises(magnific.MagnificError):
        _gen(tmp_path, sess)


def test_generate_timeout_returns_pending(tmp_path):
    sess = _FakeSession(poll_statuses=("IN_PROGRESS",))   # никогда не COMPLETED
    out = _gen(tmp_path, sess, timeout=0)
    assert out["timed_out"] is True
    assert out["images"] == [] and out["task_id"] == "tid-1"


def test_generate_invalid_key_raises(tmp_path):
    sess = _FakeSession(post_status=401, post_payload={"message": "invalid api key"})
    with pytest.raises(magnific.MagnificError) as e:
        _gen(tmp_path, sess)
    assert "401" in str(e.value) or "key" in str(e.value).lower()


def test_generate_insufficient_credits_raises(tmp_path):
    sess = _FakeSession(post_status=402, post_payload={"message": "insufficient credits"})
    with pytest.raises(magnific.MagnificError):
        _gen(tmp_path, sess)


def test_generate_network_error_raises(tmp_path):
    class _BoomSession:
        def post(self, url, **kw):
            raise requests.exceptions.ConnectionError("down")

    with pytest.raises(magnific.MagnificError):
        _gen(tmp_path, _BoomSession())


# ── FIX B: устойчивое CDN-скачивание (не терять оплаченный результат) ──────

def test_save_image_retries_then_succeeds(tmp_path):
    class _Flaky:
        def __init__(self):
            self.n = 0

        def get(self, url, **kw):
            self.n += 1
            if self.n < 3:
                raise requests.exceptions.Timeout("slow cdn")
            return _Resp(200, content=b"IMGDATA")

    sess = _Flaky()
    out = tmp_path / "o.png"
    size = magnific.save_image("http://cdn/x.png", out, session=sess,
                               retries=3, _sleep=lambda *_: None)
    assert size == len(b"IMGDATA") and out.read_bytes() == b"IMGDATA"
    assert sess.n == 3          # ретраил дважды перед успехом


def test_save_image_all_attempts_fail_raises(tmp_path):
    class _Dead:
        def __init__(self):
            self.n = 0

        def get(self, url, **kw):
            self.n += 1
            raise requests.exceptions.Timeout("cdn dead")

    sess = _Dead()
    with pytest.raises(magnific.MagnificError):
        magnific.save_image("http://cdn/x.png", tmp_path / "o.png", session=sess,
                            retries=3, _sleep=lambda *_: None)
    assert sess.n == 3          # исчерпал все попытки


def test_generate_download_failure_preserves_result(tmp_path):
    """Скачивание падает всегда, но задача COMPLETED — результат НЕ теряется (image_urls)."""
    class _SessDlFails(_FakeSession):
        def get(self, url, **kw):
            if not url.startswith(_BASE):     # download-GET с CDN
                raise requests.exceptions.Timeout("cdn down")
            return super().get(url, **kw)     # poll остаётся рабочим

    sess = _SessDlFails(generated=("https://cdn.freepik/img.png",))
    out = _gen(tmp_path, sess, download_retries=1)   # без исключения наружу
    assert out["timed_out"] is False
    assert out["images"] == []                       # локально ничего не сохранилось
    assert out["image_urls"] == ["https://cdn.freepik/img.png"]
    assert out["download_failed"] is True
    assert out["task_id"] == "tid-1"                 # номерок на месте


# ── ВИДЕО через Magnific REST (t2v veo / i2v kling) ───────────────────────

def test_build_video_payload_veo_t2v():
    path, body = magnific._build_video_payload("veo-3-1", "neon city drive",
                                               negative="blurry", duration=8, aspect="16:9")
    assert path == "/v1/ai/text-to-video/veo-3-1"
    assert body["prompt"] == "neon city drive" and body["negative_prompt"] == "blurry"
    assert body["duration"] == 8 and body["aspect_ratio"] == "16:9"
    assert "image" not in body


def test_build_video_payload_veo_rejects_bad_duration():
    with pytest.raises(magnific.MagnificError):
        magnific._build_video_payload("veo-3-1", "x", duration=5)   # 5 не в {4,6,8}


def test_build_video_payload_veo_rejects_start_frame():
    with pytest.raises(magnific.MagnificError):
        magnific._build_video_payload("veo-3-1", "x", image="https://cdn/f.png")


def test_build_video_payload_kling_i2v_url_image():
    path, body = magnific._build_video_payload("kling-v2-5-pro", "turn head", duration="5",
                                               aspect="widescreen_16_9", image="https://cdn/frame.png")
    assert path == "/v1/ai/image-to-video/kling-v2-5-pro"
    assert body["image"] == "https://cdn/frame.png"      # URL — как есть
    assert body["duration"] == "5" and body["aspect_ratio"] == "widescreen_16_9"


def test_build_video_payload_kling_local_frame_base64(tmp_path):
    frame = _png(tmp_path, "winner.png")
    path, body = magnific._build_video_payload("kling-v2-5-pro", "animate", image=str(frame))
    assert base64.b64decode(body["image"]) == b"\x89PNG\r\n\x1a\nFAKE"   # локальный кадр → base64


def test_build_video_payload_kling_requires_frame():
    with pytest.raises(magnific.MagnificError):
        magnific._build_video_payload("kling-v2-5-pro", "x")   # i2v без кадра


def test_build_video_payload_kling_rejects_bad_aspect():
    with pytest.raises(magnific.MagnificError):
        magnific._build_video_payload("kling-v2-5-pro", "x", image="https://u", aspect="16:9")  # нужен enum


def test_build_video_payload_unknown_model():
    with pytest.raises(magnific.MagnificError):
        magnific._build_video_payload("seedance", "x")


def test_generate_video_veo_happy_path(tmp_path):
    sess = _FakeSession(generated=("https://cdn/clip.mp4",), img=b"VIDEO")
    out = magnific.generate_video("neon city", tmp_path / "out", model="veo-3-1",
                                  base_url=_BASE, api_key="mk", duration=8, aspect="16:9",
                                  session=sess, poll_interval=0)
    assert out["timed_out"] is False and len(out["videos"]) == 1
    v = Path(out["videos"][0])
    assert v.exists() and v.suffix == ".mp4" and v.read_bytes() == b"VIDEO"
    assert "magnific_veo-3-1" in v.name


def test_generate_video_download_failure_preserves(tmp_path):
    class _DlFail(_FakeSession):
        def get(self, url, **kw):
            if not url.startswith(_BASE):
                raise requests.exceptions.Timeout("cdn")
            return super().get(url, **kw)

    sess = _DlFail(generated=("https://cdn/clip.mp4",))
    out = magnific.generate_video("x", tmp_path / "out", model="veo-3-1", base_url=_BASE,
                                  api_key="mk", session=sess, poll_interval=0, download_retries=1)
    assert out["videos"] == [] and out["download_failed"] is True
    assert out["video_urls"] == ["https://cdn/clip.mp4"]
