"""generation-factory MCP server: gf_generate_draft (ComfyUI) + gf_generate_final (Nano)."""

from __future__ import annotations

from pathlib import Path

from . import pricing, budget as budget_mod, media, writer as writer_mod, video_jobs as jobs_mod
from .backends import (nano as nano_mod, comfyui as comfyui_mod, dreamina as dreamina_mod,
                       magnific as magnific_mod)


def _maybe_rewrite(project, task, negative, target, *, settings, writer):
    """Авто-путь: fail-open. Возвращает (prompt, negative, prompt_log, writer_skipped)."""
    try:
        res = writer.write_prompt(project, target, task, settings=settings)
    except writer.WriterError as e:
        return task, negative, None, str(e)
    return res["prompt"], (negative or res.get("negative") or ""), res.get("log_path"), None


def _generate_draft_impl(project: str, prompt: str, n: int = 4, negative: str = "",
                         seed: int = 0, raw: bool = False, *, settings,
                         comfy=comfyui_mod, budget=budget_mod, writer=writer_mod) -> dict:
    prompt_used, neg_used, prompt_log, skipped = prompt, negative, None, None
    if not raw:
        prompt_used, neg_used, prompt_log, skipped = _maybe_rewrite(
            project, prompt, negative, settings.writer_draft_target,
            settings=settings, writer=writer)
    project_dir = Path(project)
    date = media.today()
    out_dir = media.drafts_dir(project_dir, date)
    cost = pricing.estimate("comfyui", n)  # 0.0 for local
    gate = budget.check(project_dir, cost, settings.image_cap_usd)
    if not gate["allowed"]:
        return {"error": gate["reason"], "images": [], "backend": "comfyui",
                "cost_usd": cost, "spent_usd": gate["spent"]}
    saved = comfy.generate(prompt_used, out_dir, server_url=settings.comfyui_url,
                           ckpt=settings.comfyui_ckpt, workflow_path=settings.comfyui_workflow or None,
                           n=n, negative=neg_used, seed=seed)
    budget.log_cost(project_dir, "comfyui", n, cost, note=f"draft {date}")
    return {"images": [str(p) for p in saved], "backend": "comfyui",
            "cost_usd": cost, "spent_usd": budget.spent(project_dir),
            "prompt_used": prompt_used, "prompt_log": prompt_log, "writer_skipped": skipped}


def _generate_final_impl(project: str, prompt: str, refs: "list | None" = None, aspect: str = "9:16",
                         raw: bool = False, *, settings, nano=nano_mod, budget=budget_mod,
                         writer=writer_mod) -> dict:
    prompt_used, prompt_log, skipped = prompt, None, None
    if not raw:
        prompt_used, _neg_ignored, prompt_log, skipped = _maybe_rewrite(
            project, prompt, "", settings.writer_final_target,
            settings=settings, writer=writer)
    project_dir = Path(project)
    refs = [Path(r) for r in (refs or [])]
    date = media.today()
    out_dir = media.generated_dir(project_dir, date)  # generated/<date>/
    cost = pricing.estimate("nano", 1)
    gate = budget.check(project_dir, cost, settings.image_cap_usd)
    if not gate["allowed"]:
        return {"error": gate["reason"], "images": [], "backend": "nano",
                "cost_usd": cost, "spent_usd": gate["spent"]}
    password = _nano_password(settings)
    saved = nano.generate(prompt_used, refs, out_dir, server_url=settings.nano_server_url,
                          password=password, timeout=settings.nano_timeout, aspect=aspect)
    budget.log_cost(project_dir, "nano", 1, cost, note=f"final {date}")
    return {"images": [str(p) for p in saved], "backend": "nano",
            "cost_usd": cost, "spent_usd": budget.spent(project_dir),
            "prompt_used": prompt_used, "prompt_log": prompt_log, "writer_skipped": skipped}


def _credit_note(credits: int, model: str, resolution: str) -> str:
    # Курс кредита JiMeng→USD не задан (спека §5.4) — учитываем в кредитах, cost_usd=0.
    return f"{credits} credits ({model}, {resolution})"


def _generate_video_impl(project: str, mode: str, prompt: str, image: str = "", first: str = "",
                         last: str = "", images: "list | None" = None, video: "list | None" = None,
                         audio: "list | None" = None, model: str = "", duration: int = 5,
                         ratio: str = "", resolution: str = "720p", raw: bool = False, *,
                         settings, dreamina=dreamina_mod, budget=budget_mod, writer=writer_mod,
                         jobs=jobs_mod) -> dict:
    """Сгенерировать видео через Dreamina (Seedance). Гибрид: ждёт до poll; не успел → pending."""
    model = model or settings.dreamina_default_model
    prompt_used, prompt_log, skipped = prompt, None, None
    if not raw:
        prompt_used, _neg_ignored, prompt_log, skipped = _maybe_rewrite(
            project, prompt, "", "video/seedance-2-0", settings=settings, writer=writer)

    project_dir = Path(project)
    date = media.today()
    out_dir = media.generated_dir(project_dir, date)
    credits = pricing.estimate_dreamina_credits(model, resolution, duration)

    warning = None
    if resolution == "1080p":
        warning = ("1080p у Seedance стоит ~×3 от 720p и работает только через "
                   "mode=multimodal + model=seedance2.0_vip — проверь параметры и кредиты.")

    try:
        res = dreamina.submit(mode, prompt=prompt_used, model=model, out_dir=out_dir,
                              duration=duration, ratio=ratio, resolution=resolution,
                              poll=settings.dreamina_poll_wait, image=image, first=first, last=last,
                              images=images, video=video, audio=audio, bin=settings.dreamina_bin)
    except dreamina.DreaminaError as e:
        return {"error": str(e), "backend": "dreamina", "prompt_used": prompt_used,
                "prompt_log": prompt_log, "writer_skipped": skipped}

    status = res["status"]
    output = str(res["output"]) if res.get("output") else None
    jobs.append_job(project_dir, {"submit_id": res.get("submit_id"), "mode": mode, "model": model,
                                  "task": prompt, "prompt_used": prompt_used, "resolution": resolution,
                                  "duration": duration, "status": status, "output": output,
                                  "credits": credits, "date": date})
    if status == "success":
        budget.log_cost(project_dir, f"dreamina/{model}", 1, 0.0,
                        note=_credit_note(credits, model, resolution))
    return {"status": status, "submit_id": res.get("submit_id"), "output": output,
            "backend": "dreamina", "model": model, "credits": credits,
            "prompt_used": prompt_used, "prompt_log": prompt_log, "writer_skipped": skipped,
            "warning": warning}


def _fetch_video_impl(project: str, submit_id: str, *, settings, dreamina=dreamina_mod,
                      budget=budget_mod, jobs=jobs_mod) -> dict:
    """Дозабрать готовый клип по submit_id: query_result → скачать mp4, обновить реестр, учесть кредиты."""
    project_dir = Path(project)
    date = media.today()
    out_dir = media.generated_dir(project_dir, date)
    registry = {j.get("submit_id"): j for j in jobs.read_jobs(project_dir)}
    rec = registry.get(submit_id, {})
    try:
        res = dreamina.fetch(submit_id, out_dir, mode=rec.get("mode", ""),
                             bin=settings.dreamina_bin)
    except dreamina.DreaminaError as e:
        return {"error": str(e)}

    status = res["status"]
    output = str(res["output"]) if res.get("output") else None
    if status == "success":
        jobs.update_job(project_dir, submit_id, status="success", output=output)
        credits = int(rec.get("credits", 0)) or pricing.estimate_dreamina_credits(
            rec.get("model", settings.dreamina_default_model), rec.get("resolution", "720p"),
            int(rec.get("duration", 5)))
        budget.log_cost(project_dir, f"dreamina/{rec.get('model', 'seedance')}", 1, 0.0,
                        note=_credit_note(credits, rec.get("model", "seedance"),
                                          rec.get("resolution", "720p")))
    elif status == "fail":
        jobs.update_job(project_dir, submit_id, status="fail")
    return {"status": status, "output": output, "fail_reason": res.get("fail_reason")}


def _list_video_jobs_impl(project: str, *, settings, dreamina=dreamina_mod, jobs=jobs_mod) -> dict:
    """Реестр видео-задач + живой статус из dreamina list_task (fail-open, если CLI недоступен)."""
    project_dir = Path(project)
    registry = jobs.read_jobs(project_dir)
    live = {}
    try:
        for j in dreamina.list_jobs(bin=settings.dreamina_bin):
            if j.get("submit_id"):
                live[j["submit_id"]] = j.get("status")
    except dreamina.DreaminaError:
        pass
    out = []
    for rec in registry:
        sid = rec.get("submit_id")
        out.append({"submit_id": sid, "mode": rec.get("mode"), "model": rec.get("model"),
                    "task": rec.get("task"), "status": rec.get("status"),
                    "output": rec.get("output"), "live_status": live.get(sid)})
    return {"jobs": out}


def _generate_magnific_impl(project: str, model: str, prompt: str, refs: "list | None" = None,
                            aspect: str = "", raw: bool = False, *, settings,
                            magnific=magnific_mod, budget=budget_mod, writer=writer_mod) -> dict:
    """Сгенерировать картинку через Magnific (Freepik). Клон _generate_final_impl; model обязателен."""
    # ранние чистые отказы (fail-closed) до траты денег/токенов
    if model not in magnific._MODELS:
        return {"error": f"Неизвестная модель Magnific {model!r} "
                         f"(доступны: {sorted(magnific._MODELS)})", "images": []}
    if not settings.magnific_api_key:
        return {"error": "Нет GF_MAGNIFIC_API_KEY — укажи ключ Magnific в .env.", "images": []}

    prompt_used, prompt_log, skipped = prompt, None, None
    if not raw:
        prompt_used, _neg_ignored, prompt_log, skipped = _maybe_rewrite(
            project, prompt, "", f"magnific/{model}", settings=settings, writer=writer)

    project_dir = Path(project)
    refs = [str(r) for r in (refs or [])]
    date = media.today()
    out_dir = media.generated_dir(project_dir, date)
    cost = pricing.estimate_magnific(model, 1)
    gate = budget.check(project_dir, cost, settings.image_cap_usd)
    if not gate["allowed"]:
        return {"error": gate["reason"], "images": [], "backend": "magnific",
                "model": model, "cost_usd": cost, "spent_usd": gate["spent"]}

    try:
        res = magnific.generate(prompt_used, refs, out_dir, model=model,
                                base_url=settings.magnific_base_url,
                                api_key=settings.magnific_api_key, aspect=aspect,
                                timeout=settings.magnific_timeout,
                                poll_interval=settings.magnific_poll_interval)
    except magnific.MagnificError as e:
        return {"error": str(e), "images": [], "backend": "magnific", "model": model,
                "prompt_used": prompt_used, "prompt_log": prompt_log, "writer_skipped": skipped}

    images = [str(p) for p in res.get("images", [])]
    if images:   # трату логируем только по факту картинки (не при timed_out без результата)
        budget.log_cost(project_dir, f"magnific/{model}", 1, cost, note=f"magnific {date}")
    return {"images": images, "backend": "magnific", "model": model,
            "cost_usd": cost, "spent_usd": budget.spent(project_dir),
            "prompt_used": prompt_used, "prompt_log": prompt_log, "writer_skipped": skipped,
            "task_id": res.get("task_id"), "timed_out": res.get("timed_out", False)}


def _write_prompt_impl(project: str, target: str, task: str, refs: "list | None" = None,
                       aspect: str = "", extra: str = "", *, settings, writer=writer_mod) -> dict:
    try:
        return writer.write_prompt(project, target, task, refs=refs or None,
                                   aspect=aspect or None, extra=extra or None,
                                   settings=settings)
    except writer.WriterError as e:
        return {"error": str(e)}


def _nano_password(settings) -> "str | None":
    """Read NITRO_BANANA_APP_PASSWORD from env or the nitro env file."""
    import os
    pw = os.environ.get("NITRO_BANANA_APP_PASSWORD")
    if pw:
        return pw
    env_file = Path(settings.nano_env_file) if settings.nano_env_file else (
        Path.home() / ".lionfilms" / "nitro_banana.env")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("NITRO_BANANA_APP_PASSWORD="):
                return line.split("=", 1)[1].strip()
    return None


def _make_bearer_middleware(token: str):
    import hmac
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class BearerAuth(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            header = request.headers.get("authorization", "")
            if not hmac.compare_digest(header, f"Bearer {token}"):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await call_next(request)

    return BearerAuth


def build_server():
    from mcp.server.fastmcp import FastMCP
    from .core import build_core
    settings = build_core().settings
    mcp = FastMCP("generation-factory", host=settings.mcp_bind, port=settings.mcp_port)

    @mcp.tool()
    def gf_generate_draft(project: str, prompt: str, n: int = 4,
                          negative: str = "", seed: int = 0, raw: bool = False) -> dict:
        """Generate N cheap ComfyUI drafts. prompt = задача (райтер перепишет);
        raw=True — текст уходит в модель дословно."""
        return _generate_draft_impl(project, prompt, n, negative, seed, raw, settings=settings)

    @mcp.tool()
    def gf_generate_final(project: str, prompt: str, refs: "list | None" = None,
                          aspect: str = "9:16", raw: bool = False) -> dict:
        """Generate a client-facing final with Nano Banana. prompt = задача (райтер перепишет);
        raw=True — дословно."""
        return _generate_final_impl(project, prompt, refs, aspect, raw, settings=settings)

    @mcp.tool()
    def gf_write_prompt(project: str, target: str, task: str, refs: "list | None" = None,
                        aspect: str = "", extra: str = "") -> dict:
        """Написать промпт для цели (target из gf_list_targets) по паспорту модели.
        Работает и для площадок, которые завод не оборачивает (magnific/*)."""
        return _write_prompt_impl(project, target, task, refs, aspect, extra, settings=settings)

    @mcp.tool()
    def gf_list_targets() -> dict:
        """Доступные цели промпт-райтера (из frontmatter'ов паспортов)."""
        try:
            return {"targets": writer_mod.list_targets()}
        except writer_mod.WriterError as e:
            return {"error": str(e)}

    @mcp.tool()
    def gf_generate_video(project: str, mode: str, prompt: str,
                          image: str = "", first: str = "", last: str = "",
                          images: "list | None" = None, video: "list | None" = None,
                          audio: "list | None" = None, model: str = "",
                          duration: int = 5, ratio: str = "", resolution: str = "720p",
                          raw: bool = False) -> dict:
        """Сгенерировать видео через Dreamina (Seedance). mode: i2v|t2v|frames|multimodal.
        prompt = задача движения (райтер перепишет по video/seedance-2-0); raw=True — дословно.
        Гибрид: ждёт до GF_DREAMINA_POLL_WAIT сек; не успел → submit_id (pending) в реестр.
        i2v: image (обычно winner). Возвращает status/submit_id/output/prompt_used/credits/warning."""
        return _generate_video_impl(project, mode, prompt, image, first, last, images, video,
                                    audio, model, duration, ratio, resolution, raw, settings=settings)

    @mcp.tool()
    def gf_list_video_jobs(project: str) -> dict:
        """Реестр видео-задач проекта + их живой статус (из dreamina list_task)."""
        return _list_video_jobs_impl(project, settings=settings)

    @mcp.tool()
    def gf_fetch_video(project: str, submit_id: str) -> dict:
        """Дозабрать готовый клип по номерку: query_result → mp4 в media/generated/<date>/,
        обновить реестр, учесть кредиты. querying → ещё не готово; fail → причина; success → путь."""
        return _fetch_video_impl(project, submit_id, settings=settings)

    @mcp.tool()
    def gf_generate_magnific(project: str, model: str, prompt: str,
                             refs: "list | None" = None, aspect: str = "",
                             raw: bool = False) -> dict:
        """Сгенерировать картинку через Magnific (Freepik). model обязателен:
        mystic (t2i) | seedream-v4-5-edit (1-5 рефов, лицо+локация) | flux-kontext-pro (1 реф).
        prompt = задача (райтер перепишет по magnific/<model>); raw=True — дословно.
        refs — локальные пути (base64 в тело). aspect — enum Magnific (square_1_1, widescreen_16_9…).
        Гибрид: таймаут → task_id + timed_out=true (Hermes может дозабрать позже)."""
        return _generate_magnific_impl(project, model, prompt, refs, aspect, raw, settings=settings)

    from . import curate

    @mcp.tool()
    def gf_add_variant(project: str, image_path: str, set_id: str,
                       note: str = "", date: str = "", stage: str = "") -> dict:
        """Copy an image into a variant set under a canonical name (source untouched).
        set_id = '<kind>/<name>', kinds: lineart|final|cast|look-and-feel|brand|location."""
        return curate.add_variant(project, image_path, set_id, note=note,
                                  date=date or None, stage=stage or None)

    @mcp.tool()
    def gf_set_winner(project: str, set_id: str, image_path: str) -> dict:
        """Point a set's movable winner at a file inside the project (no pixel moves)."""
        return curate.set_winner(project, set_id, image_path)

    @mcp.tool()
    def gf_list_sets(project: str, kind: str = "") -> dict:
        """Inventory of variant sets: counts, current winners, homes."""
        return curate.list_sets(project, kind=kind or None)

    @mcp.tool()
    def gf_materialize_winners(project: str) -> dict:
        """Rebuild the winners/ projection folder from the manifest + history."""
        return curate.materialize_winners(project)

    @mcp.tool()
    def gf_discard(project: str, image_path: str) -> dict:
        """Soft-delete a media file into _TO_PURGE (verified copy; never hard-delete)."""
        return curate.discard(project, image_path)

    @mcp.tool()
    def gf_adopt_set(project: str, set_id: str, dir: str) -> dict:
        """Register an existing folder as a set's history (no files are moved)."""
        return curate.adopt_set(project, set_id, dir)

    return mcp, settings


def run_server(http: bool = False):
    mcp, settings = build_server()
    if not http:
        mcp.run(transport="stdio")
        return
    if settings.mcp_token:
        import uvicorn

        inner = mcp.streamable_http_app()
        inner.add_middleware(_make_bearer_middleware(settings.mcp_token))
        uvicorn.run(inner, host=settings.mcp_bind, port=settings.mcp_port)
    else:
        mcp.run(transport="streamable-http")
