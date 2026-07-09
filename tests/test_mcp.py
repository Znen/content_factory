from pathlib import Path
import pytest
from gf.config import Settings
from gf.mcp_server import _generate_draft_impl, _generate_final_impl


def _settings(tmp_path, cap=None):
    return Settings(
        comfyui_url="http://127.0.0.1:8188", comfyui_ckpt="m.safetensors",
        comfyui_workflow="", nano_server_url="http://localhost:3001", nano_env_file="",
        nano_timeout=120, image_cap_usd=cap, mcp_bind="127.0.0.1", mcp_port=8766,
        mcp_token=None, writer_model="claude-sonnet-5", writer_max_tokens=2000,
        writer_enabled=False, writer_draft_target="comfyui/sdxl-juggernaut",
        writer_final_target="nano/gemini-image", dreamina_bin="dreamina",
        dreamina_poll_wait=180, dreamina_default_model="seedance2.0fast",
        magnific_api_key="mk-test", magnific_base_url="https://api.magnific.com",
        magnific_timeout=180, magnific_poll_interval=3,
        magnific_download_timeout=120, magnific_download_retries=3)


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


# ── видео-бэкенд Dreamina: gf_generate_video / list / fetch ────────────────

_DreaminaError = __import__("gf.backends.dreamina", fromlist=["DreaminaError"]).DreaminaError


class _FakeDreamina:
    DreaminaError = _DreaminaError

    def __init__(self, submit_result=None, submit_error=None, fetch_result=None, jobs=None):
        self.submit_result = submit_result or {"status": "success", "submit_id": "sid1",
                                               "output": "/x/clip.mp4"}
        self.submit_error = submit_error
        self.fetch_result = fetch_result
        self._jobs = jobs or []
        self.submit_calls = []

    def submit(self, mode, **kw):
        self.submit_calls.append((mode, kw))
        if self.submit_error:
            raise self.DreaminaError(self.submit_error)
        return self.submit_result

    def fetch(self, submit_id, out_dir, **kw):
        return self.fetch_result

    def list_jobs(self, **kw):
        return self._jobs


def _gen_video(tmp_path, **kw):
    from gf.mcp_server import _generate_video_impl
    return _generate_video_impl(str(tmp_path), settings=_settings(tmp_path), **kw)


def test_generate_video_raw_true_skips_writer(tmp_path):
    w = _OkAutoWriter()
    d = _FakeDreamina()
    out = _gen_video(tmp_path, mode="t2v", prompt="as is", raw=True, writer=w, dreamina=d)
    assert w.calls == []
    assert out["prompt_used"] == "as is"
    assert out["writer_skipped"] is None
    assert out["backend"] == "dreamina"


def test_generate_video_auto_uses_seedance_target(tmp_path):
    w = _OkAutoWriter()
    d = _FakeDreamina()
    out = _gen_video(tmp_path, mode="i2v", prompt="оживить портрет", image="w.png",
                     writer=w, dreamina=d)
    assert w.calls == ["video/seedance-2-0"]
    assert out["prompt_used"] == "REWRITTEN"
    # промпт движения ушёл в submit
    mode, kw = d.submit_calls[0]
    assert mode == "i2v" and kw["prompt"] == "REWRITTEN"


def test_generate_video_pending_records_registry_no_budget(tmp_path):
    from gf import video_jobs
    d = _FakeDreamina(submit_result={"status": "pending", "submit_id": "sidP", "output": None})
    out = _gen_video(tmp_path, mode="t2v", prompt="neon", raw=True, writer=_OkAutoWriter(), dreamina=d)
    assert out["status"] == "pending" and out["submit_id"] == "sidP"
    jobs = video_jobs.read_jobs(tmp_path)
    assert jobs and jobs[-1]["submit_id"] == "sidP" and jobs[-1]["status"] == "pending"
    # трата не логируется, пока нет success
    assert not (tmp_path / "media" / ".gf_cost_log.jsonl").exists()


def test_generate_video_success_logs_credits_and_registry(tmp_path):
    import json
    from gf import video_jobs
    d = _FakeDreamina(submit_result={"status": "success", "submit_id": "sidS",
                                     "output": str(tmp_path / "clip.mp4")})
    out = _gen_video(tmp_path, mode="t2v", prompt="neon", model="seedance2.0_vip",
                     resolution="720p", duration=5, raw=True, writer=_OkAutoWriter(), dreamina=d)
    assert out["status"] == "success" and out["credits"] == 70
    jobs = video_jobs.read_jobs(tmp_path)
    assert jobs[-1]["status"] == "success"
    rec = json.loads((tmp_path / "media" / ".gf_cost_log.jsonl").read_text().splitlines()[-1])
    assert "70" in rec["note"] and "credit" in rec["note"].lower()


def test_generate_video_writer_failure_fail_open(tmp_path):
    d = _FakeDreamina()
    out = _gen_video(tmp_path, mode="t2v", prompt="задача", writer=_FailAutoWriter(), dreamina=d)
    assert out["writer_skipped"] == "ключ протух"
    mode, kw = d.submit_calls[0]
    assert kw["prompt"] == "задача"   # сырой текст ушёл в генерацию


def test_generate_video_dreamina_error_fail_closed(tmp_path):
    d = _FakeDreamina(submit_error="Dreamina не залогинен: dreamina login --headless")
    out = _gen_video(tmp_path, mode="t2v", prompt="x", raw=True, writer=_OkAutoWriter(), dreamina=d)
    assert "error" in out and "login" in out["error"].lower()


def test_generate_video_1080p_warning(tmp_path):
    d = _FakeDreamina(submit_result={"status": "pending", "submit_id": "s", "output": None})
    out = _gen_video(tmp_path, mode="multimodal", prompt="x", model="seedance2.0_vip",
                     resolution="1080p", raw=True, writer=_OkAutoWriter(), dreamina=d)
    assert out.get("warning") and "1080p" in out["warning"]


def test_fetch_video_success_updates_registry_and_credits(tmp_path):
    import json
    from gf import video_jobs
    from gf.mcp_server import _fetch_video_impl
    video_jobs.append_job(tmp_path, {"submit_id": "sidF", "mode": "t2v",
                                     "model": "seedance2.0_vip", "resolution": "720p",
                                     "duration": 5, "status": "pending", "output": None})
    d = _FakeDreamina(fetch_result={"status": "success",
                                    "output": tmp_path / "got.mp4", "fail_reason": None})
    out = _fetch_video_impl(str(tmp_path), "sidF", settings=_settings(tmp_path), dreamina=d)
    assert out["status"] == "success"
    assert video_jobs.read_jobs(tmp_path)[0]["status"] == "success"
    rec = json.loads((tmp_path / "media" / ".gf_cost_log.jsonl").read_text().splitlines()[-1])
    assert "credit" in rec["note"].lower()


def test_list_video_jobs_merges_registry_and_live(tmp_path):
    from gf import video_jobs
    from gf.mcp_server import _list_video_jobs_impl
    video_jobs.append_job(tmp_path, {"submit_id": "sidL", "mode": "t2v", "status": "pending"})
    d = _FakeDreamina(jobs=[{"submit_id": "sidL", "status": "success", "raw": {}}])
    out = _list_video_jobs_impl(str(tmp_path), settings=_settings(tmp_path), dreamina=d)
    assert out["jobs"] and out["jobs"][0]["submit_id"] == "sidL"
    assert out["jobs"][0]["live_status"] == "success"


def test_video_tools_registered():
    import asyncio
    from gf.mcp_server import build_server
    mcp, _ = build_server()
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"gf_generate_video", "gf_list_video_jobs", "gf_fetch_video"} <= names


# ── Magnific-бэкенд: gf_generate_magnific ─────────────────────────────────

_MagnificError = __import__("gf.backends.magnific", fromlist=["MagnificError"]).MagnificError
_MAGN_MODELS = __import__("gf.backends.magnific", fromlist=["_MODELS"])._MODELS


class _FakeMagnific:
    MagnificError = _MagnificError
    _MODELS = _MAGN_MODELS

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def generate(self, prompt, refs, out_dir, **kw):
        self.calls.append((prompt, kw))
        if self.error:
            raise self.MagnificError(self.error)
        if self.result is not None:
            return self.result
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "magnific_seedream_x.png"
        p.write_bytes(b"IMG")
        return {"images": [p], "task_id": "tid-9", "timed_out": False}


def _gen_magn(tmp_path, **kw):
    from gf.mcp_server import _generate_magnific_impl
    s = kw.pop("settings", None) or _settings(tmp_path)
    return _generate_magnific_impl(str(tmp_path), settings=s, **kw)


def test_magnific_raw_true_skips_writer(tmp_path):
    w = _OkAutoWriter()
    m = _FakeMagnific()
    out = _gen_magn(tmp_path, model="mystic", prompt="as is", raw=True, writer=w, magnific=m)
    assert w.calls == []
    assert out["prompt_used"] == "as is"
    assert out["backend"] == "magnific" and out["model"] == "mystic"
    assert out["task_id"] == "tid-9" and out["timed_out"] is False


def test_magnific_auto_uses_model_target(tmp_path):
    w = _OkAutoWriter()
    m = _FakeMagnific()
    out = _gen_magn(tmp_path, model="seedream-v4-5-edit", prompt="оживить",
                    refs=["r.png"], writer=w, magnific=m)
    assert w.calls == ["magnific/seedream-v4-5-edit"]
    assert out["prompt_used"] == "REWRITTEN"
    assert m.calls[0][0] == "REWRITTEN"


def test_magnific_unknown_model_clean_error(tmp_path):
    m = _FakeMagnific()
    out = _gen_magn(tmp_path, model="nope", prompt="x", raw=True,
                    writer=_OkAutoWriter(), magnific=m)
    assert "error" in out and "mystic" in out["error"]
    assert m.calls == []            # бэкенд не вызван


def test_magnific_no_api_key_fail_closed(tmp_path):
    s = _settings(tmp_path)
    s.magnific_api_key = None
    m = _FakeMagnific()
    out = _gen_magn(tmp_path, model="mystic", prompt="x", raw=True,
                    settings=s, writer=_OkAutoWriter(), magnific=m)
    assert "error" in out and "GF_MAGNIFIC_API_KEY" in out["error"]
    assert m.calls == []


def test_magnific_budget_gate_blocks(tmp_path):
    s = _settings(tmp_path, cap=0.0)
    m = _FakeMagnific()
    out = _gen_magn(tmp_path, model="mystic", prompt="x", raw=True,
                    settings=s, writer=_OkAutoWriter(), magnific=m)
    assert "error" in out and out["images"] == []
    assert m.calls == []            # до траты


def test_magnific_writer_failure_fail_open(tmp_path):
    m = _FakeMagnific()
    out = _gen_magn(tmp_path, model="mystic", prompt="задача",
                    writer=_FailAutoWriter(), magnific=m)
    assert out["writer_skipped"] == "ключ протух"
    assert m.calls[0][0] == "задача"    # сырой текст ушёл в генерацию


def test_magnific_error_fail_closed(tmp_path):
    m = _FakeMagnific(error="Magnific: нет доступа/кредитов (HTTP 402)")
    out = _gen_magn(tmp_path, model="mystic", prompt="x", raw=True,
                    writer=_OkAutoWriter(), magnific=m)
    assert "error" in out and "402" in out["error"]


def test_magnific_timed_out_no_budget_log(tmp_path):
    m = _FakeMagnific(result={"images": [], "task_id": "tid-P", "timed_out": True})
    out = _gen_magn(tmp_path, model="mystic", prompt="x", raw=True,
                    writer=_OkAutoWriter(), magnific=m)
    assert out["timed_out"] is True and out["task_id"] == "tid-P"
    assert out["images"] == []
    assert not (tmp_path / "media" / ".gf_cost_log.jsonl").exists()   # трата без картинки не логируется


def test_magnific_success_logs_cost(tmp_path):
    import json
    m = _FakeMagnific()
    out = _gen_magn(tmp_path, model="seedream-v4-5-edit", prompt="x", refs=["r.png"],
                    raw=True, writer=_OkAutoWriter(), magnific=m)
    assert len(out["images"]) == 1 and out["cost_usd"] > 0
    rec = json.loads((tmp_path / "media" / ".gf_cost_log.jsonl").read_text().splitlines()[-1])
    assert rec["backend"] == "magnific/seedream-v4-5-edit"


def test_magnific_tool_registered():
    import asyncio
    from gf.mcp_server import build_server
    mcp, _ = build_server()
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert "gf_generate_magnific" in names


# ── FIX A: относительный project → fail-closed ДО траты/записи ─────────────

def test_draft_relative_project_fail_closed(tmp_path):
    w = _OkAutoWriter()
    out = _generate_draft_impl("ingosstrakh", "task", 1, "", 0,
                               settings=_settings(tmp_path), comfy=_FakeComfy(), writer=w)
    assert "error" in out and "абсолют" in out["error"].lower() and "ingosstrakh" in out["error"]
    assert out["images"] == []
    assert w.calls == []            # guard до райтера — токены не потрачены


def test_final_relative_project_fail_closed(tmp_path):
    w = _OkAutoWriter()
    out = _generate_final_impl("ingosstrakh", "task", [], "9:16",
                               settings=_settings(tmp_path), nano=_FakeNano(), writer=w)
    assert "error" in out and out["images"] == [] and w.calls == []


def test_magnific_relative_project_fail_closed(tmp_path):
    from gf.mcp_server import _generate_magnific_impl
    w = _OkAutoWriter()
    m = _FakeMagnific()
    out = _generate_magnific_impl("ingosstrakh", "mystic", "x",
                                  settings=_settings(tmp_path), writer=w, magnific=m)
    assert "error" in out and "абсолют" in out["error"].lower()
    assert m.calls == [] and w.calls == []


def test_video_relative_project_fail_closed(tmp_path):
    from gf.mcp_server import _generate_video_impl
    d = _FakeDreamina()
    out = _generate_video_impl("ingosstrakh", "t2v", "x",
                               settings=_settings(tmp_path), dreamina=d, writer=_OkAutoWriter())
    assert "error" in out and "абсолют" in out["error"].lower()
    assert d.submit_calls == []


# ── FIX B: gf_generate_magnific пробрасывает CDN-URL при упавшем скачивании ─

def test_magnific_download_failed_surfaces_urls_and_logs_cost(tmp_path):
    m = _FakeMagnific(result={"images": [], "task_id": "tid-X", "timed_out": False,
                              "image_urls": ["https://cdn.freepik/img.png"],
                              "download_failed": True})
    out = _gen_magn(tmp_path, model="mystic", prompt="x", raw=True,
                    writer=_OkAutoWriter(), magnific=m)
    assert out["download_failed"] is True
    assert out["image_urls"] == ["https://cdn.freepik/img.png"]
    assert out["images"] == []
    assert out["task_id"] == "tid-X"
    assert out.get("warning")                       # предупреждение о ручном заборе
    # оплаченный результат (задача COMPLETED) → стоимость логируется даже без локальной картинки
    assert (tmp_path / "media" / ".gf_cost_log.jsonl").exists()
