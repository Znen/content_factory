"""Тесты видео-бэкенда Dreamina (Seedance). Инъецируемый _runner, без живого CLI."""
import json
from pathlib import Path

import pytest
from PIL import Image

from gf.backends import dreamina


# ── staging + shrink ──────────────────────────────────────────────────────

def test_stage_and_shrink_removes_spaces_and_fits_720p(tmp_path):
    src_dir = tmp_path / "with space"
    src_dir.mkdir()
    src = src_dir / "key frame.png"
    Image.new("RGB", (3000, 2000), (120, 130, 140)).save(src)

    staged = dreamina.stage_and_shrink(src, "720p", staging_dir=tmp_path / "stage")

    assert staged.exists()
    assert " " not in str(staged)              # no-space путь — критично для Dreamina
    assert staged.stat().st_size < 500_000     # <500KB для 720p
    w, h = Image.open(staged).size
    assert w <= 1280 and h <= 720              # вписан в 720p-бокс


def test_stage_and_shrink_1080p_box_and_cap(tmp_path):
    src = tmp_path / "big.png"
    Image.new("RGB", (4000, 3000), (10, 20, 30)).save(src)

    staged = dreamina.stage_and_shrink(src, "1080p", staging_dir=tmp_path / "stage")

    assert staged.stat().st_size < 1_000_000   # <1MB для 1080p
    w, h = Image.open(staged).size
    assert w <= 1920 and h <= 1080


def test_stage_and_shrink_converts_rgba(tmp_path):
    src = tmp_path / "rgba.png"
    Image.new("RGBA", (800, 600), (10, 20, 30, 128)).save(src)
    staged = dreamina.stage_and_shrink(src, "720p", staging_dir=tmp_path / "stage")
    assert Image.open(staged).mode == "RGB"    # JPEG не держит альфу


# ── сборка команды (§4: маппинг режимов; i2v без --ratio) ─────────────────

def test_build_cmd_i2v_has_image_no_ratio():
    cmd = dreamina._build_cmd("dreamina", "i2v", prompt="turn head", model="seedance2.0fast",
                              duration=5, ratio="16:9", resolution="720p", poll=180,
                              image="/tmp/a.jpg")
    assert cmd[:2] == ["dreamina", "image2video"]
    assert "--image=/tmp/a.jpg" in cmd
    assert not any(c.startswith("--ratio=") for c in cmd)            # i2v ratio берёт из картинки
    assert not any(c.startswith("--video_resolution=") for c in cmd)
    assert "--poll=180" in cmd and "--duration=5" in cmd
    assert "--model_version=seedance2.0fast" in cmd


def test_build_cmd_t2v_has_ratio_and_resolution():
    cmd = dreamina._build_cmd("dreamina", "t2v", prompt="neon city", model="seedance2.0",
                              duration=10, ratio="16:9", resolution="720p", poll=180)
    assert cmd[:2] == ["dreamina", "text2video"]
    assert "--ratio=16:9" in cmd and "--video_resolution=720p" in cmd
    assert not any(c.startswith("--image=") for c in cmd)


def test_build_cmd_frames_has_first_last_no_ratio():
    cmd = dreamina._build_cmd("dreamina", "frames", prompt="summer to winter",
                              model="seedance2.0", duration=8, ratio="", resolution="720p",
                              poll=180, first="/tmp/s.jpg", last="/tmp/e.jpg")
    assert cmd[:2] == ["dreamina", "frames2video"]
    assert "--first=/tmp/s.jpg" in cmd and "--last=/tmp/e.jpg" in cmd
    assert not any(c.startswith("--ratio=") for c in cmd)


def test_build_cmd_multimodal_repeats_inputs():
    cmd = dreamina._build_cmd("dreamina", "multimodal", prompt="reveal", model="seedance2.0_vip",
                              duration=10, ratio="16:9", resolution="1080p", poll=180,
                              images=["/tmp/a.jpg", "/tmp/b.jpg"], video=["/tmp/v.mp4"],
                              audio=["/tmp/m.mp3"])
    assert cmd[:2] == ["dreamina", "multimodal2video"]
    assert "--image=/tmp/a.jpg" in cmd and "--image=/tmp/b.jpg" in cmd
    assert "--video=/tmp/v.mp4" in cmd and "--audio=/tmp/m.mp3" in cmd
    assert "--video_resolution=1080p" in cmd


def test_build_cmd_unknown_mode_raises():
    with pytest.raises(dreamina.DreaminaError):
        dreamina._build_cmd("dreamina", "bogus", prompt="x", model="m", duration=5,
                            ratio="", resolution="720p", poll=180)


# ── фейковый _runner: отвечает на команду генерации и на query_result ─────

class _CP:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeRunner:
    """cmd[1] решает ответ. query_result --download_dir пишет фейковый mp4."""
    def __init__(self, *, gen_stdout='{"submit_id":"abc123","status":"success"}',
                 gen_rc=0, gen_fail_first=False, query_stdout='{"submit_id":"abc123","status":"success"}',
                 list_stdout='{"tasks":[]}'):
        self.calls = []
        self.gen_stdout = gen_stdout
        self.gen_rc = gen_rc
        self.gen_fail_first = gen_fail_first
        self.query_stdout = query_stdout
        self.list_stdout = list_stdout
        self._gen_calls = 0

    def __call__(self, cmd, cwd):
        self.calls.append((list(cmd), Path(cwd)))
        sub = cmd[1] if len(cmd) > 1 else ""
        if sub == "query_result":
            ddir = next((c.split("=", 1)[1] for c in cmd if c.startswith("--download_dir=")), None)
            if ddir and '"status":"success"' in self.query_stdout.replace(" ", ""):
                Path(ddir).mkdir(parents=True, exist_ok=True)
                (Path(ddir) / "result.mp4").write_bytes(b"VIDEO")
            return _CP(0, self.query_stdout)
        if sub == "list_task":
            return _CP(0, self.list_stdout)
        # команда генерации
        self._gen_calls += 1
        if self.gen_fail_first and self._gen_calls == 1:
            return _CP(1, "", "upload image: upload phase, no file upload")
        return _CP(self.gen_rc, self.gen_stdout)


def _img(tmp_path, name="frame.png", size=(800, 600)):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (100, 110, 120)).save(p)
    return p


# ── submit: гибрид poll + retry ───────────────────────────────────────────

def test_submit_i2v_success_downloads_and_no_ratio(tmp_path):
    img = _img(tmp_path / "in", "hero shot.png")   # пробел в имени
    out_dir = tmp_path / "out"
    runner = _FakeRunner(gen_stdout='{"submit_id":"abc123","status":"success"}')
    res = dreamina.submit("i2v", prompt="turn head", model="seedance2.0fast",
                          out_dir=out_dir, duration=5, resolution="720p", poll=180,
                          image=img, staging_dir=tmp_path / "stage", _runner=runner,
                          bin="dreamina")
    assert res["status"] == "success"
    assert res["submit_id"] == "abc123"
    assert res["output"] and Path(res["output"]).exists()
    assert Path(res["output"]).read_bytes() == b"VIDEO"
    # команда генерации: image2video, staged image без пробелов, без --ratio
    gen = next(c for c, _ in runner.calls if c[1] == "image2video")
    img_arg = next(a for a in gen if a.startswith("--image="))
    assert " " not in img_arg
    assert not any(a.startswith("--ratio=") for a in gen)


def test_submit_timeout_returns_pending_with_submit_id(tmp_path):
    runner = _FakeRunner(gen_stdout='{"submit_id":"xyz789","status":"querying"}')
    res = dreamina.submit("t2v", prompt="neon city", model="seedance2.0",
                          out_dir=tmp_path / "out", duration=10, ratio="16:9",
                          resolution="720p", poll=30, _runner=runner, bin="dreamina")
    assert res["status"] == "pending"
    assert res["submit_id"] == "xyz789"
    assert res["output"] is None
    # query_result НЕ вызывался (нечего скачивать)
    assert not any(c[1] == "query_result" for c, _ in runner.calls)


def test_submit_retries_flaky_upload(tmp_path):
    img = _img(tmp_path / "in")
    runner = _FakeRunner(gen_fail_first=True)   # первый вызов — flaky upload, второй — успех
    res = dreamina.submit("i2v", prompt="x", model="seedance2.0fast",
                          out_dir=tmp_path / "out", duration=5, image=img,
                          staging_dir=tmp_path / "stage", _runner=runner,
                          bin="dreamina", _sleep=lambda *_: None)
    assert res["status"] == "success"
    gen_calls = [c for c, _ in runner.calls if c[1] == "image2video"]
    assert len(gen_calls) == 2   # ретрай сработал


def test_submit_pre_tns_raises_with_hint(tmp_path):
    img = _img(tmp_path / "in")
    runner = _FakeRunner(gen_rc=1, gen_stdout="generation failed: pre-TNS check did not pass")
    with pytest.raises(dreamina.DreaminaError) as e:
        dreamina.submit("i2v", prompt="x", model="seedance2.0fast",
                        out_dir=tmp_path / "out", duration=5, image=img,
                        staging_dir=tmp_path / "stage", _runner=runner, bin="dreamina",
                        _sleep=lambda *_: None)
    assert "pre-TNS" in str(e.value) or "фильтр" in str(e.value).lower()


def test_submit_not_logged_in_raises(tmp_path):
    runner = _FakeRunner(gen_rc=1, gen_stdout="", )
    runner.gen_stdout = "error: not logged in, please run dreamina login"
    with pytest.raises(dreamina.DreaminaError) as e:
        dreamina.submit("t2v", prompt="x", model="seedance2.0", out_dir=tmp_path / "out",
                        duration=5, _runner=runner, bin="dreamina", _sleep=lambda *_: None)
    assert "login" in str(e.value).lower()


# ── fetch + list_jobs ──────────────────────────────────────────────────────

def test_fetch_success_downloads_mp4(tmp_path):
    runner = _FakeRunner(query_stdout='{"submit_id":"abc123","status":"success"}')
    r = dreamina.fetch("abc123", tmp_path / "out", mode="i2v", bin="dreamina", _runner=runner)
    assert r["status"] == "success"
    assert Path(r["output"]).exists() and Path(r["output"]).suffix == ".mp4"
    assert "seedance_i2v" in Path(r["output"]).name


def test_fetch_querying_returns_none(tmp_path):
    runner = _FakeRunner(query_stdout='{"submit_id":"abc123","status":"querying"}')
    r = dreamina.fetch("abc123", tmp_path / "out", bin="dreamina", _runner=runner)
    assert r["status"] == "querying" and r["output"] is None


def test_fetch_fail_carries_reason(tmp_path):
    runner = _FakeRunner(query_stdout='{"submit_id":"abc123","status":"fail","fail_reason":"nsfw blocked"}')
    r = dreamina.fetch("abc123", tmp_path / "out", bin="dreamina", _runner=runner)
    assert r["status"] == "fail" and "nsfw" in r["fail_reason"]


def test_fetch_ghost_task_no_history(tmp_path):
    runner = _FakeRunner(query_stdout="no history found")
    r = dreamina.fetch("ghost", tmp_path / "out", bin="dreamina", _runner=runner)
    assert r["status"] == "no_history" and r["output"] is None
    assert "призрак" in r["fail_reason"] or "no history" in r["fail_reason"]


def test_list_jobs_parses_statuses(tmp_path):
    runner = _FakeRunner(list_stdout='{"tasks":[{"submit_id":"a","gen_status":"success"},'
                                     '{"submit_id":"b","gen_status":"querying"}]}')
    jobs = dreamina.list_jobs(bin="dreamina", _runner=runner)
    by_id = {j["submit_id"]: j["status"] for j in jobs}
    assert by_id == {"a": "success", "b": "querying"}
