from pathlib import Path
from gf.config import Settings
from gf.mcp_server import _generate_draft_impl, _generate_final_impl


def _settings(tmp_path, cap=None):
    return Settings(
        comfyui_url="http://127.0.0.1:8188", comfyui_ckpt="m.safetensors",
        comfyui_workflow="", nano_server_url="http://localhost:3001", nano_env_file="",
        nano_timeout=120, image_cap_usd=cap, mcp_bind="127.0.0.1", mcp_port=8766,
        mcp_token=None, writer_model="claude-sonnet-5", writer_max_tokens=2000,
        writer_enabled=False, writer_draft_target="comfyui/sdxl-juggernaut",
        writer_final_target="nano/gemini-image")


class _FakeComfy:
    def generate(self, prompt, out_dir, **kw):
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for i in range(1, kw.get("n", 4) + 1):
            p = out_dir / f"draft-{i:02d}.png"
            p.write_bytes(b"x")
            paths.append(p)
        return paths


class _FakeNano:
    def generate(self, prompt, refs, out_dir, **kw):
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "nano_final.png"
        p.write_bytes(b"y")
        return [p]


def test_draft_impl_generates_and_is_free(tmp_path):
    s = _settings(tmp_path)
    out = _generate_draft_impl(str(tmp_path), "a cat", 2, "", 0, raw=True,
                               settings=s, comfy=_FakeComfy())
    assert out["backend"] == "comfyui"
    assert out["cost_usd"] == 0.0
    assert len(out["images"]) == 2
    assert all(Path(p).exists() for p in out["images"])


def test_final_impl_generates_and_logs_cost(tmp_path):
    s = _settings(tmp_path)
    out = _generate_final_impl(str(tmp_path), "cinematic", [], "9:16", raw=True,
                               settings=s, nano=_FakeNano())
    assert out["backend"] == "nano"
    assert out["cost_usd"] > 0
    assert out["spent_usd"] >= out["cost_usd"]
    # cost logged
    assert (tmp_path / "media" / ".gf_cost_log.jsonl").exists()


def test_final_impl_blocked_by_cap(tmp_path):
    s = _settings(tmp_path, cap=0.0)
    out = _generate_final_impl(str(tmp_path), "cinematic", [], "9:16", raw=True,
                               settings=s, nano=_FakeNano())
    assert "error" in out
    assert out["images"] == []
    # nothing generated
    assert not any((tmp_path / "media").rglob("nano_*.png"))


class _OkAutoWriter:
    from gf.writer import WriterError  # class attr, чтобы except writer.WriterError работал

    def __init__(self):
        self.calls = []

    def write_prompt(self, project, target, task, refs=None, aspect=None, extra=None, *, settings):
        self.calls.append(target)
        return {"prompt": "REWRITTEN", "negative": "auto-neg", "params": {"steps": 50},
                "notes": None, "target": target, "log_path": "/tmp/log.md", "warning": None}


class _FailAutoWriter:
    from gf.writer import WriterError

    def write_prompt(self, *a, **kw):
        raise self.WriterError("ключ протух")


def test_draft_raw_true_bypasses_writer(tmp_path):
    w = _OkAutoWriter()
    out = _generate_draft_impl(str(tmp_path), "as is", 1, "", 0, raw=True,
                               settings=_settings(tmp_path), comfy=_FakeComfy(), writer=w)
    assert w.calls == []
    assert out["prompt_used"] == "as is"
    assert out["writer_skipped"] is None


def test_draft_auto_rewrites_and_reports(tmp_path):
    w = _OkAutoWriter()
    out = _generate_draft_impl(str(tmp_path), "задача", 1, "", 0,
                               settings=_settings(tmp_path), comfy=_FakeComfy(), writer=w)
    assert w.calls == ["comfyui/sdxl-juggernaut"]
    assert out["prompt_used"] == "REWRITTEN"
    assert out["prompt_log"] == "/tmp/log.md"


def test_draft_explicit_negative_wins(tmp_path):
    captured = {}

    class _Comfy(_FakeComfy):
        def generate(self, prompt, out_dir, **kw):
            captured.update(kw, prompt=prompt)
            return super().generate(prompt, out_dir, **kw)

    _generate_draft_impl(str(tmp_path), "задача", 1, "my-neg", 0,
                         settings=_settings(tmp_path), comfy=_Comfy(), writer=_OkAutoWriter())
    assert captured["prompt"] == "REWRITTEN"
    assert captured["negative"] == "my-neg"  # явный негатив главнее авто


def test_draft_writer_failure_falls_open(tmp_path):
    out = _generate_draft_impl(str(tmp_path), "задача", 1, "", 0,
                               settings=_settings(tmp_path), comfy=_FakeComfy(),
                               writer=_FailAutoWriter())
    assert out["writer_skipped"] == "ключ протух"
    assert out["prompt_used"] == "задача"     # генерация прошла сырым текстом
    assert len(out["images"]) == 1


def test_final_auto_uses_final_target(tmp_path):
    w = _OkAutoWriter()
    out = _generate_final_impl(str(tmp_path), "задача", [], "9:16",
                               settings=_settings(tmp_path), nano=_FakeNano(), writer=w)
    assert w.calls == ["nano/gemini-image"]
    assert out["prompt_used"] == "REWRITTEN"


def test_bearer_auth_middleware_rejects_bad_token():
    import asyncio
    from gf.mcp_server import _make_bearer_middleware
    cls = _make_bearer_middleware("secret")
    mw = cls(app=lambda scope, receive, send: None)

    class _Req:
        def __init__(self, auth):
            self.headers = {"authorization": auth} if auth is not None else {}

    async def _next(req):
        from starlette.responses import PlainTextResponse
        return PlainTextResponse("ok")

    async def _run(auth):
        return await mw.dispatch(_Req(auth), _next)

    assert asyncio.run(_run(None)).status_code == 401
    assert asyncio.run(_run("Bearer wrong")).status_code == 401
    assert asyncio.run(_run("Bearer secret")).status_code == 200


def test_curation_tools_registered():
    import asyncio
    from gf.mcp_server import build_server
    mcp, _ = build_server()
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"gf_add_variant", "gf_set_winner", "gf_list_sets",
            "gf_materialize_winners", "gf_discard", "gf_adopt_set"} <= names


def test_write_prompt_impl_maps_writer_error(tmp_path):
    from gf.mcp_server import _write_prompt_impl

    class _BoomWriter:
        WriterError = __import__("gf.writer", fromlist=["WriterError"]).WriterError

        def write_prompt(self, *a, **kw):
            raise self.WriterError("нет такой цели")

    out = _write_prompt_impl(str(tmp_path), "magnific/nope", "задача",
                             settings=_settings(tmp_path), writer=_BoomWriter())
    assert out == {"error": "нет такой цели"}


def test_write_prompt_impl_passes_through(tmp_path):
    from gf.mcp_server import _write_prompt_impl

    class _OkWriter:
        WriterError = __import__("gf.writer", fromlist=["WriterError"]).WriterError

        def write_prompt(self, project, target, task, refs=None, aspect=None, extra=None, *, settings):
            return {"prompt": "p", "target": target, "negative": None,
                    "params": None, "notes": None, "log_path": None, "warning": None}

    out = _write_prompt_impl(str(tmp_path), "comfyui/sdxl-test", "задача",
                             settings=_settings(tmp_path), writer=_OkWriter())
    assert out["prompt"] == "p"


def test_writer_tools_registered():
    import asyncio
    from gf.mcp_server import build_server
    mcp, _ = build_server()
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"gf_write_prompt", "gf_list_targets"} <= names
