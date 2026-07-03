import json
from pathlib import Path
import pytest
from gf.backends import comfyui


def test_load_bundled_workflow():
    wf = comfyui.load_workflow(None)
    assert wf["4"]["class_type"] == "CheckpointLoaderSimple"
    assert "9" in wf and wf["9"]["class_type"] == "SaveImage"


def test_build_workflow_substitutes():
    tpl = comfyui.load_workflow(None)
    wf = comfyui.build_workflow(tpl, ckpt="m.safetensors", prompt="a cat",
                                negative="blurry", n=3, seed=42, width=768,
                                height=512, steps=15, cfg=6.0)
    assert wf["4"]["inputs"]["ckpt_name"] == "m.safetensors"
    assert wf["6"]["inputs"]["text"] == "a cat"
    assert wf["7"]["inputs"]["text"] == "blurry"
    assert wf["5"]["inputs"]["batch_size"] == 3
    assert wf["5"]["inputs"]["width"] == 768 and wf["5"]["inputs"]["height"] == 512
    assert wf["3"]["inputs"]["seed"] == 42 and wf["3"]["inputs"]["steps"] == 15
    assert wf["3"]["inputs"]["cfg"] == 6.0
    # original template not mutated
    assert tpl["4"]["inputs"]["ckpt_name"] == "PLACEHOLDER_CKPT"


class _Resp:
    def __init__(self, status, *, jsondata=None, content=b""):
        self.status_code = status
        self._json = jsondata
        self.content = content
        self.text = json.dumps(jsondata) if jsondata is not None else ""

    def json(self):
        return self._json


class _FakeSession:
    def __init__(self):
        self.pid = "pid-1"

    def post(self, url, **kw):
        assert url.endswith("/prompt")
        return _Resp(200, jsondata={"prompt_id": self.pid})

    def get(self, url, **kw):
        if "/history/" in url:
            return _Resp(200, jsondata={self.pid: {"outputs": {"9": {"images": [
                {"filename": "gf_draft_0001.png", "subfolder": "", "type": "output"},
                {"filename": "gf_draft_0002.png", "subfolder": "", "type": "output"},
            ]}}}})
        if "/view" in url:
            return _Resp(200, content=b"IMGBYTES")
        return _Resp(404)


def test_generate_downloads_images(tmp_path):
    out = tmp_path / "drafts"
    saved = comfyui.generate("a cat", out, server_url="http://127.0.0.1:8188",
                             ckpt="m.safetensors", n=2, session=_FakeSession(),
                             poll_interval=0.0)
    assert len(saved) == 2
    assert all(p.exists() and p.read_bytes() == b"IMGBYTES" for p in saved)
    assert saved[0].name == "draft-01.png" and saved[1].name == "draft-02.png"
