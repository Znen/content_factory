import base64
import json
from pathlib import Path
import pytest
from gf.backends import nano


def _png(tmp_path, name):
    p = tmp_path / name
    p.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
    return p


def test_encode_inputs_base64_and_mime(tmp_path):
    p = _png(tmp_path, "ref.png")
    b64s, mimes = nano.encode_inputs([p])
    assert mimes == ["image/png"]
    assert base64.b64decode(b64s[0]) == b"\x89PNG\r\n\x1a\nFAKE"


def test_encode_rejects_unsupported(tmp_path):
    bad = tmp_path / "x.gif"
    bad.write_bytes(b"GIF")
    with pytest.raises(ValueError):
        nano.encode_inputs([bad])


def test_save_image_data_uri(tmp_path):
    raw = b"hello-png-bytes"
    data_uri = "data:image/png;base64," + base64.b64encode(raw).decode()
    out = tmp_path / "o.png"
    n = nano.save_image(data_uri, out)
    assert out.read_bytes() == raw and n == len(raw)


class _FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeSession:
    """Minimal requests-like stub: login then /api/gemini."""
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/api/auth/login"):
            return _FakeResp(200, {"token": "tok-123"})
        if url.endswith("/api/gemini"):
            raw = base64.b64encode(b"final-image").decode()
            return _FakeResp(200, {"imageUrl": "data:image/png;base64," + raw})
        return _FakeResp(404, {"error": "nope"})


def test_generate_writes_final(tmp_path):
    ref = _png(tmp_path, "face.png")
    out_dir = tmp_path / "out"
    sess = _FakeSession()
    saved = nano.generate(
        "make it cinematic", [ref], out_dir,
        server_url="http://localhost:3001", password="pw",
        token_cache=tmp_path / "tok.json", session=sess,
    )
    assert len(saved) == 1 and saved[0].exists()
    assert saved[0].read_bytes() == b"final-image"
    # login happened + gemini payload carried base64 refs
    gemini_call = [c for c in sess.calls if c[0].endswith("/api/gemini")][0]
    body = gemini_call[1]["json"]
    assert body["action"] == "edit"
    assert len(body["base64Datas"]) == 1 and body["mimeTypes"] == ["image/png"]


def test_generate_rejects_more_than_4_refs(tmp_path):
    refs = [_png(tmp_path, f"r{i}.png") for i in range(5)]
    with pytest.raises(nano.NanoError):
        nano.generate("x", refs, tmp_path / "o",
                      server_url="http://localhost:3001", password="pw",
                      token_cache=tmp_path / "t.json", session=_FakeSession())
