"""Dreamina CLI (JiMeng / 即梦, ByteDance) — видео-бэкенд завода (Seedance).

Subprocess-обёртка над бинарём `dreamina`. По образцу старого
`videogen/backends/dreamina.py`: инъецируемый `_runner(cmd, cwd) -> CompletedProcess`,
свои исключения, никакой связи с бюджетом/проектом (это в mcp_server.py).

Async-модель Dreamina: submit -> `submit_id` -> `query_result [--download_dir]`;
`--poll=N` ждёт терминальный статус в терминале. Статусы: querying / success / fail.

⚠️ Точный формат stdout CLI не зафиксирован по help-дампу (живой CLI недоступен при
разработке). Парсер (`_parse_result`) толерантен: сначала пробует JSON, затем regex по
`submit_id`/статусу/`fail_reason`. Если реальный CLI отдаёт иначе — правь `_parse_result`
и отметь расхождение (спека §4/§11).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

# resolution-matching rule (из DREAMINA_CLI.md, проверено вживую):
# 720p -> 1280x720 q85 <500KB ; 1080p -> 1920x1080 q92 <1MB
_RES_MATCH = {
    "720p": {"box": (1280, 720), "quality": 85, "cap": 500_000},
    "1080p": {"box": (1920, 1080), "quality": 92, "cap": 1_000_000},
}
_QUALITY_FLOOR = 40


class DreaminaError(Exception):
    pass


def _sanitize(name: str) -> str:
    """Имя файла без пробелов/проблемных символов (Dreamina тихо роняет пути с пробелами)."""
    stem = Path(name).stem
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in stem)
    return (safe or "input") + ".jpg"


def stage_and_shrink(path: "str | Path", resolution: str = "720p",
                     staging_dir: "str | Path | None" = None) -> Path:
    """Копия входной картинки в no-space temp + ресайз/сжатие под resolution-matching.

    720p -> вписать в 1280x720, q85, <500KB; 1080p -> 1920x1080, q92, <1MB.
    Возвращает путь к staged JPEG (без пробелов). Требует Pillow.
    """
    from PIL import Image

    src = Path(path)
    if not src.exists():
        raise DreaminaError(f"Input file not found: {src}")
    rule = _RES_MATCH.get(resolution, _RES_MATCH["720p"])

    if staging_dir is None:
        import tempfile
        staging_dir = Path(tempfile.mkdtemp(prefix="gf_dreamina_"))
    staging_dir = Path(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    out = staging_dir / _sanitize(src.name)

    img = Image.open(src)
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail(rule["box"], Image.LANCZOS)   # вписать в бокс, сохранив пропорции

    quality = rule["quality"]
    while True:
        img.save(out, "JPEG", quality=quality)
        if out.stat().st_size <= rule["cap"] or quality <= _QUALITY_FLOOR:
            break
        quality -= 5
    return out


def _stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# mode -> команда Dreamina CLI (§4)
_MODE_CMD = {
    "i2v": "image2video",
    "t2v": "text2video",
    "frames": "frames2video",
    "multimodal": "multimodal2video",
}
# режимы, принимающие --ratio / --video_resolution (i2v/frames — из картинки/кадров)
_RATIO_MODES = {"t2v", "multimodal"}


def _build_cmd(bin: str, mode: str, *, prompt: str, model: str, duration: int,
               ratio: str = "", resolution: str = "720p", poll: int = 180,
               image: str = "", first: str = "", last: str = "",
               images: "list | None" = None, video: "list | None" = None,
               audio: "list | None" = None) -> "list[str]":
    """Собрать argv для dreamina <command>. Пути входов уже staged (без пробелов).

    i2v (image2video) НЕ принимает --ratio (берётся из картинки); frames — тоже.
    --ratio/--video_resolution только для t2v/multimodal.
    """
    cmd_name = _MODE_CMD.get(mode)
    if cmd_name is None:
        raise DreaminaError(
            f"Unknown mode {mode!r} (valid: {sorted(_MODE_CMD)})")
    cmd = [bin, cmd_name, f"--prompt={prompt}", f"--model_version={model}",
           f"--duration={duration}"]
    if mode == "i2v":
        cmd.append(f"--image={image}")
    elif mode == "frames":
        cmd += [f"--first={first}", f"--last={last}"]
    elif mode == "multimodal":
        for p in (images or []):
            cmd.append(f"--image={p}")
        for p in (video or []):
            cmd.append(f"--video={p}")
        for p in (audio or []):
            cmd.append(f"--audio={p}")
    if mode in _RATIO_MODES:
        if ratio:
            cmd.append(f"--ratio={ratio}")
        if resolution:
            cmd.append(f"--video_resolution={resolution}")
    cmd.append(f"--poll={poll}")
    return cmd


# ── вызов CLI, парсинг, классификация ошибок ──────────────────────────────

import subprocess  # noqa: E402


def _default_runner(cmd: "list[str]", cwd: "Path"):
    try:
        return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    except FileNotFoundError as e:
        raise DreaminaError(
            f"Бинарь Dreamina не найден ({cmd[0]!r}). Установи и залогинь: "
            f"`dreamina login --headless` (или задай GF_DREAMINA_BIN). ({e})") from e


def _parse_result(text: str) -> dict:
    """Извлечь {submit_id, status, fail_reason} из вывода CLI. Сначала JSON, затем regex.
    Формат stdout по help-дампу не зафиксирован — толерантный парс (см. docstring модуля)."""
    import json
    import re
    text = text or ""
    # 1) JSON (весь вывод или встроенный объект)
    for candidate in (text.strip(), *re.findall(r"\{.*?\}", text, re.DOTALL)):
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict) and ("submit_id" in obj or "status" in obj):
            return {"submit_id": obj.get("submit_id"),
                    "status": _norm_status(str(obj.get("status") or "")),
                    "fail_reason": obj.get("fail_reason")}
    # 2) regex-fallback
    sid = re.search(r"submit_id[\"'\s:=]+([0-9a-fA-F]{6,})", text)
    fr = re.search(r"fail_reason[\"'\s:=]+(.+)", text)
    return {"submit_id": sid.group(1) if sid else None,
            "status": _norm_status(text),
            "fail_reason": fr.group(1).strip() if fr else None}


def _norm_status(text: str) -> str:
    low = (text or "").lower()
    if "success" in low:
        return "success"
    if "fail" in low:
        return "fail"
    if "querying" in low or "queue" in low:
        return "querying"
    return ""


def _raise_for_known_errors(text: str) -> None:
    """Специфичные ошибки Dreamina → DreaminaError с понятной подсказкой (§7)."""
    low = (text or "").lower()
    if "pre-tns" in low:
        raise DreaminaError(
            "Контент отклонён фильтром Dreamina (pre-TNS): убери акцент на теле, добавь "
            "одежду, целься камерой в лицо. Кредиты могли списаться — не ретрай вслепую.")
    if "aigccomplianceconfirmationrequired" in low.replace(" ", ""):
        raise DreaminaError(
            "Dreamina требует подтверждения модели: подтверди на сайте Dreamina Web и повтори.")
    if "not logged in" in low or "please login" in low or "please run dreamina login" in low \
            or "unauthorized" in low:
        raise DreaminaError(
            "Dreamina не залогинен: выполни `dreamina login --headless` и повтори.")
    if ("insufficient" in low and "credit" in low) or "not enough credit" in low:
        raise DreaminaError("Недостаточно кредитов JiMeng для генерации.")


def _is_flaky_upload(text: str) -> bool:
    low = (text or "").lower()
    return "no file upload" in low or "upload phase" in low


def _stage_inputs(mode, *, image, first, last, images, resolution, staging_dir):
    """Стейджинг+сжатие входных КАРТИНОК под режим. Возвращает dict с staged-путями."""
    def _s(p):
        return str(stage_and_shrink(p, resolution, staging_dir=staging_dir))
    out = {}
    if mode == "i2v" and image:
        out["image"] = _s(image)
    elif mode == "frames":
        if first:
            out["first"] = _s(first)
        if last:
            out["last"] = _s(last)
    elif mode == "multimodal" and images:
        out["images"] = [_s(p) for p in images]
    return out


def fetch(submit_id: str, out_dir: "str | Path", *, mode: str = "",
          bin: str = "dreamina", _runner=None) -> dict:
    """query_result --submit_id --download_dir. Возвращает
    {status: success|querying|fail|no_history, output: Path|None, fail_reason: str|None}."""
    import shutil
    import tempfile
    _runner = _runner or _default_runner
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dl = Path(tempfile.mkdtemp(prefix="gf_dl_"))
    cmd = [bin, "query_result", f"--submit_id={submit_id}", f"--download_dir={dl}"]
    cp = _runner(cmd, out_dir)
    text = (cp.stdout or "") + "\n" + (cp.stderr or "")
    if "no history" in text.lower():
        return {"status": "no_history", "output": None,
                "fail_reason": "no history found (задача-призрак — проверь ~/.dreamina_cli/logs)"}
    parsed = _parse_result(text)
    if parsed["status"] == "success":
        mp4s = sorted(dl.glob("*.mp4"), key=lambda p: p.stat().st_mtime)
        if not mp4s:
            return {"status": "querying", "output": None, "fail_reason": None}
        stem = f"seedance_{mode}_{_stamp()}" if mode else f"seedance_{_stamp()}"
        dest = out_dir / f"{stem}.mp4"
        shutil.move(str(mp4s[-1]), str(dest))
        return {"status": "success", "output": dest, "fail_reason": None}
    if parsed["status"] == "fail":
        return {"status": "fail", "output": None,
                "fail_reason": parsed.get("fail_reason") or "unknown"}
    return {"status": "querying", "output": None, "fail_reason": None}


def submit(mode: str, *, prompt: str, model: str, out_dir: "str | Path",
           duration: int = 5, ratio: str = "", resolution: str = "720p", poll: int = 180,
           image: "str | Path" = "", first: "str | Path" = "", last: "str | Path" = "",
           images: "list | None" = None, video: "list | None" = None,
           audio: "list | None" = None, staging_dir: "str | Path | None" = None,
           bin: str = "dreamina", attempts: int = 3, base_delay: float = 3.0,
           _runner=None, _sleep=None) -> dict:
    """Запустить генерацию (гибрид). Стейджит+сжимает картинки, шеллит dreamina <cmd> --poll.
    success за poll → скачивает mp4; иначе → {status: pending, submit_id}. Retry на flaky upload."""
    import time
    _runner = _runner or _default_runner
    _sleep = _sleep or time.sleep
    out_dir = Path(out_dir)

    staged = _stage_inputs(mode, image=image, first=first, last=last, images=images,
                           resolution=resolution, staging_dir=staging_dir)
    video = [str(p) for p in (video or [])]
    audio = [str(p) for p in (audio or [])]
    cmd = _build_cmd(bin, mode, prompt=prompt, model=model, duration=duration,
                     ratio=ratio, resolution=resolution, poll=poll,
                     image=staged.get("image", ""), first=staged.get("first", ""),
                     last=staged.get("last", ""), images=staged.get("images"),
                     video=video, audio=audio)

    cp = None
    for attempt in range(1, max(1, attempts) + 1):
        cp = _runner(cmd, out_dir)
        text = (cp.stdout or "") + "\n" + (cp.stderr or "")
        if cp.returncode != 0 and _is_flaky_upload(text) and attempt < attempts:
            _sleep(base_delay * attempt)
            continue
        break

    text = (cp.stdout or "") + "\n" + (cp.stderr or "")
    _raise_for_known_errors(text)
    if cp.returncode != 0:
        raise DreaminaError(f"Dreamina вернул rc={cp.returncode}: {text.strip()[:300]}")

    parsed = _parse_result(text)
    submit_id = parsed["submit_id"]
    if parsed["status"] == "success":
        r = fetch(submit_id, out_dir, mode=mode, bin=bin, _runner=_runner)
        return {"status": r["status"], "submit_id": submit_id, "output": r["output"]}
    if parsed["status"] == "fail":
        raise DreaminaError(f"Dreamina задача провалилась: {parsed.get('fail_reason') or text.strip()[:200]}")
    return {"status": "pending", "submit_id": submit_id, "output": None}


def list_jobs(*, bin: str = "dreamina", _runner=None) -> "list[dict]":
    """dreamina list_task → список задач со статусами (для сверки с реестром).
    Каждый элемент: {submit_id, status, raw}."""
    import json
    _runner = _runner or _default_runner
    cp = _runner([bin, "list_task"], Path("."))
    try:
        obj = json.loads((cp.stdout or "").strip())
    except (json.JSONDecodeError, ValueError):
        return []
    tasks = obj.get("tasks", []) if isinstance(obj, dict) else obj
    out = []
    for t in (tasks or []):
        if isinstance(t, dict):
            out.append({"submit_id": t.get("submit_id"),
                        "status": _norm_status(str(t.get("gen_status") or t.get("status") or "")),
                        "raw": t})
    return out
