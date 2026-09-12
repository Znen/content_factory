"""generation-factory MCP server: gf_generate_draft (ComfyUI) + gf_generate_final (Nano)."""

from __future__ import annotations

from pathlib import Path

from . import pricing, budget as budget_mod, media, writer as writer_mod, video_jobs as jobs_mod
from .backends import (nano as nano_mod, comfyui as comfyui_mod, dreamina as dreamina_mod,
                       magnific as magnific_mod, fal as fal_mod,
                       replicate as replicate_mod, higgsfield as higgsfield_mod)


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
    try:
        media.require_absolute_project(project)
    except ValueError as e:
        return {"error": str(e), "images": []}
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
    try:
        media.require_absolute_project(project)
    except ValueError as e:
        return {"error": str(e), "images": []}
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


def _run_dreamina_video(project: str, mode: str, prompt: str, image: str = "", first: str = "",
                        last: str = "", images: "list | None" = None, video: "list | None" = None,
                        audio: "list | None" = None, model: str = "", duration: int = 5,
                        ratio: str = "", resolution: str = "720p", raw: bool = False, *,
                        settings, dreamina=dreamina_mod, budget=budget_mod, writer=writer_mod,
                        jobs=jobs_mod) -> dict:
    """Видео через Dreamina (Seedance). Гибрид: ждёт до poll; не успел → pending.
    project-guard делает диспетчер _generate_video_impl."""
    model = model or settings.dreamina_default_model
    prompt_used, prompt_log, skipped = prompt, None, None
    if not raw:
        prompt_used, _neg_ignored, prompt_log, skipped = _maybe_rewrite(
            project, prompt, "", "video/seedance-2-0", settings=settings, writer=writer)

    project_dir = Path(project)
    date = media.today()
    out_dir = media.video_dir(project_dir, date)   # видео — в generated/<date>/video/
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


# ── Magnific как ВТОРОЙ видео-путь (резерв Dreamina) ──────────────────────

_CONCURRENCY_MARKERS = ("1310", "exceedconcurrencylimit", "concurrency")
_RATIO_TO_KLING = {"16:9": "widescreen_16_9", "9:16": "social_story_9_16", "1:1": "square_1_1"}


def _is_concurrency_limit(msg: str) -> bool:
    """Dreamina ExceedConcurrencyLimit / ret=1310 → сигнал к авто-фолбэку на Magnific."""
    low = (msg or "").lower()
    return any(m in low for m in _CONCURRENCY_MARKERS)


def _coerce_video_duration(video_models: dict, model: str, d):
    """duration под enum модели (veo: 4|6|8 int; kling: '5'|'10' str). Невалидное → первое валидное."""
    durs = video_models[model]["durations"]
    for cand in (d, str(d)):
        if cand in durs:
            return cand
    return sorted(durs, key=lambda x: int(x))[0]


def _coerce_video_aspect(video_models: dict, model: str, ratio: str) -> str:
    """aspect под модель: veo — обычный '16:9'; kling — enum. Неизвестное → '' (дефолт модели)."""
    if not ratio:
        return ""
    aspects = video_models[model]["aspects"]
    if ratio in aspects:
        return ratio
    mapped = _RATIO_TO_KLING.get(ratio)
    return mapped if mapped in aspects else ""


def _run_magnific_video(project: str, mode: str, task: str, image: str, model: str,
                        duration_in, ratio_in: str, raw: bool, *, settings, magnific=magnific_mod,
                        budget=budget_mod, writer=writer_mod, jobs=jobs_mod,
                        fallback: bool = False) -> dict:
    """Видео через Magnific REST. model пуст → вывод из mode (i2v→kling, иначе veo)."""
    model = model or ("kling-v2-5-pro" if mode == "i2v" else "veo-3-1")
    if model not in magnific._VIDEO_MODELS:
        return {"error": f"Неизвестная magnific-видео-модель {model!r} "
                         f"(доступны: {sorted(magnific._VIDEO_MODELS)})", "status": "error"}
    if not settings.magnific_api_key:
        return {"error": "Нет GF_MAGNIFIC_API_KEY — укажи ключ Magnific в .env.", "status": "error"}

    # цель райтера: veo → video/veo-3-1; kling → magnific/kling-v2-5-pro (паспорта есть)
    target = "video/veo-3-1" if model == "veo-3-1" else "magnific/kling-v2-5-pro"
    prompt_used, prompt_log, skipped = task, None, None
    if not raw:
        prompt_used, _neg, prompt_log, skipped = _maybe_rewrite(
            project, task, "", target, settings=settings, writer=writer)

    project_dir = Path(project)
    date = media.today()
    out_dir = media.video_dir(project_dir, date)   # видео — в generated/<date>/video/
    duration = _coerce_video_duration(magnific._VIDEO_MODELS, model, duration_in)
    aspect = _coerce_video_aspect(magnific._VIDEO_MODELS, model, ratio_in)

    try:
        res = magnific.generate_video(prompt_used, out_dir, model=model,
                                      base_url=settings.magnific_base_url,
                                      api_key=settings.magnific_api_key, duration=duration,
                                      aspect=aspect, image=image, timeout=settings.magnific_timeout,
                                      poll_interval=settings.magnific_poll_interval,
                                      download_timeout=settings.magnific_download_timeout,
                                      download_retries=settings.magnific_download_retries)
    except magnific.MagnificError as e:
        out = {"error": str(e), "backend": "magnific", "model": model, "status": "error",
               "prompt_used": prompt_used, "prompt_log": prompt_log, "writer_skipped": skipped}
        if fallback:
            out["fallback"] = "magnific"
        return out

    videos = [str(p) for p in res.get("videos", [])]
    video_urls = res.get("video_urls") or []
    output = videos[0] if videos else None
    cost = pricing.estimate_magnific(model, 1)
    if res.get("timed_out"):
        status = "pending"
    else:
        status = "success"
    jobs.append_job(project_dir, {"submit_id": res.get("task_id"), "mode": mode, "model": model,
                                  "task": task, "prompt_used": prompt_used, "backend": "magnific",
                                  "status": status, "output": output, "date": date})
    if videos or video_urls:   # задача COMPLETED (кредиты списаны) → логируем трату
        budget.log_cost(project_dir, f"magnific/{model}", 1, cost, note=f"magnific video {date}")
    out = {"status": status, "backend": "magnific", "model": model, "output": output,
           "videos": videos, "task_id": res.get("task_id"),
           "timed_out": res.get("timed_out", False), "cost_usd": cost,
           "spent_usd": budget.spent(project_dir), "prompt_used": prompt_used,
           "prompt_log": prompt_log, "writer_skipped": skipped}
    if fallback:
        out["fallback"] = "magnific"
    # Kling i2v держит пропорцию ВХОДНОГО кадра — aspect_ratio на i2v не применяется.
    if model.startswith("kling") and (ratio_in or aspect):
        out["warning"] = ("Kling i2v держит пропорцию ВХОДНОГО кадра — aspect_ratio на i2v "
                          "не применяется. Готовь стартовый кадр в целевом соотношении "
                          "(16:9 → 1536×864 или 1920×1080).")
    if res.get("download_failed"):   # более срочное предупреждение перекрывает
        out["video_urls"] = video_urls
        out["download_failed"] = True
        out["warning"] = ("Видео не скачалось с CDN (кредиты уже списаны) — забери по "
                          "video_urls вручную, результат не потерян.")
    return out


def _generate_video_impl(project: str, mode: str, prompt: str, image: str = "", first: str = "",
                         last: str = "", images: "list | None" = None, video: "list | None" = None,
                         audio: "list | None" = None, model: str = "", duration: int = 5,
                         ratio: str = "", resolution: str = "720p", raw: bool = False,
                         backend: str = "", *, settings, dreamina=dreamina_mod,
                         magnific=magnific_mod, budget=budget_mod, writer=writer_mod,
                         jobs=jobs_mod) -> dict:
    """Диспетчер видео. backend: ""(auto по model)|dreamina|magnific|auto. При ExceedConcurrencyLimit
    (ret=1310) у Dreamina — авто-фолбэк на Magnific (i2v→kling, t2v→veo) с флагом fallback."""
    try:
        media.require_absolute_project(project)
    except ValueError as e:
        return {"error": str(e), "status": "error"}

    # авто-роутинг: явная Magnific-видео-модель без явного backend="dreamina" → Magnific
    # (Dreamina её не знает — иначе молча ушла бы в CLI и упала). Пустая model → по backend.
    if model and model in magnific._VIDEO_MODELS and backend != "dreamina":
        backend = "magnific"
    elif not backend:
        backend = "dreamina"

    if backend == "magnific":
        return _run_magnific_video(project, mode, prompt, image, model, duration, ratio, raw,
                                   settings=settings, magnific=magnific, budget=budget,
                                   writer=writer, jobs=jobs)

    res = _run_dreamina_video(project, mode, prompt, image, first, last, images, video, audio,
                              model, duration, ratio, resolution, raw, settings=settings,
                              dreamina=dreamina, budget=budget, writer=writer, jobs=jobs)
    if (backend in ("dreamina", "auto") and isinstance(res, dict)
            and "error" in res and _is_concurrency_limit(res["error"])):
        return _run_magnific_video(project, mode, prompt, image, "", duration, ratio, raw,
                                   settings=settings, magnific=magnific, budget=budget,
                                   writer=writer, jobs=jobs, fallback=True)
    return res


def _fetch_video_impl(project: str, submit_id: str, *, settings, dreamina=dreamina_mod,
                      budget=budget_mod, jobs=jobs_mod) -> dict:
    """Дозабрать готовый клип по submit_id: query_result → скачать mp4, обновить реестр, учесть кредиты."""
    project_dir = Path(project)
    date = media.today()
    out_dir = media.video_dir(project_dir, date)   # дозабор видео — тоже в video/
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
    try:
        media.require_absolute_project(project)
    except ValueError as e:
        return {"error": str(e), "images": []}
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
                                poll_interval=settings.magnific_poll_interval,
                                download_timeout=settings.magnific_download_timeout,
                                download_retries=settings.magnific_download_retries)
    except magnific.MagnificError as e:
        return {"error": str(e), "images": [], "backend": "magnific", "model": model,
                "prompt_used": prompt_used, "prompt_log": prompt_log, "writer_skipped": skipped}

    images = [str(p) for p in res.get("images", [])]
    image_urls = res.get("image_urls") or []
    # задача COMPLETED (есть картинка ИЛИ несохранённый CDN-URL) → кредиты списаны, логируем трату.
    # timed_out без результата — не логируем (трата учтётся при дозаборе).
    if images or image_urls:
        budget.log_cost(project_dir, f"magnific/{model}", 1, cost, note=f"magnific {date}")
    out = {"images": images, "backend": "magnific", "model": model,
           "cost_usd": cost, "spent_usd": budget.spent(project_dir),
           "prompt_used": prompt_used, "prompt_log": prompt_log, "writer_skipped": skipped,
           "task_id": res.get("task_id"), "timed_out": res.get("timed_out", False)}
    if res.get("download_failed"):
        out["image_urls"] = image_urls
        out["download_failed"] = True
        out["warning"] = ("Часть результатов не скачалась с CDN (кредиты уже списаны) — "
                          "забери картинку по image_urls вручную, результат не потерян.")
    return out


def _fal_pricing_note() -> str:
    return "fal.ai pricing is endpoint-specific; cost_usd is not estimated by this factory."


def _fal_output_view(res: dict) -> dict:
    output = res.get("output") if isinstance(res, dict) else None
    if not isinstance(output, dict):
        return {}
    view = {}
    if "images" in output:
        view["images"] = output["images"]
    if "image" in output:
        view["image"] = output["image"]
    if "video" in output:
        view["video"] = output["video"]
    if "audio" in output:
        view["audio"] = output["audio"]
    if "files" in output:
        view["files"] = output["files"]
    if "url" in output:
        view["url"] = output["url"]
    return view


def _fal_run_impl(project: str, endpoint: str, input: dict, wait_seconds: "int | None" = None,
                  *, settings, fal=fal_mod) -> dict:
    try:
        media.require_absolute_project(project)
    except ValueError as e:
        return {"error": str(e), "status": "error", "backend": "fal", "endpoint": endpoint}
    try:
        if hasattr(fal, "validate_endpoint_id"):
            fal.validate_endpoint_id(endpoint)
        if not isinstance(input, dict):
            raise fal.FalError("fal input must be a JSON object")
    except fal.FalError as e:
        return {"error": str(e), "status": "error", "backend": "fal", "endpoint": endpoint,
                "cost_usd": None, "pricing_note": _fal_pricing_note()}
    if not settings.fal_key:
        return {"error": "Missing FAL_KEY. Set FAL_KEY in .env to use fal.ai.",
                "status": "error", "backend": "fal", "endpoint": endpoint,
                "cost_usd": None, "pricing_note": _fal_pricing_note()}
    wait_budget = settings.fal_timeout if wait_seconds is None else int(wait_seconds)
    out_dir = media.generated_dir(Path(project), media.today())
    try:
        res = fal.run(endpoint, input, api_key=settings.fal_key,
                      queue_url=settings.fal_queue_url, timeout=settings.fal_timeout,
                      wait_seconds=wait_budget,
                      poll_interval=settings.fal_poll_interval,
                      download_timeout=settings.fal_download_timeout,
                      out_dir=out_dir)
    except fal.FalError as e:
        return {"error": str(e), "status": "error", "backend": "fal", "endpoint": endpoint,
                "cost_usd": None, "pricing_note": _fal_pricing_note()}
    out = {"backend": "fal", "endpoint": endpoint, "status": res.get("status"),
           "request_id": res.get("request_id"), "cost_usd": None,
           "pricing_note": _fal_pricing_note()}
    if res.get("status") == "pending":
        out.update({"status_url": res.get("status_url"), "response_url": res.get("response_url")})
        return out
    out.update({"outputs": _fal_output_view(res), "raw_output": res.get("output"),
                "media": res.get("media", {}), "media_urls": res.get("media_urls", [])})
    warnings = res.get("warnings") or []
    if warnings:
        out["warnings"] = warnings
    return out


def _fal_list_workflows_impl(search: str = "", used_endpoint_ids: str = "", limit: int = 50,
                             cursor: str = "", *, settings, fal=fal_mod) -> dict:
    try:
        res = fal.list_workflows(api_key=settings.fal_key, api_url=settings.fal_api_url,
                                 limit=limit, cursor=cursor, search=search,
                                 used_endpoint_ids=used_endpoint_ids,
                                 timeout=settings.fal_timeout)
    except fal.FalError as e:
        return {"error": str(e), "status": "error", "backend": "fal"}
    return {"backend": "fal", "workflows": res.get("workflows", []),
            "next_cursor": res.get("next_cursor"), "has_more": res.get("has_more"),
            "total": res.get("total")}


def _replicate_pricing_note() -> str:
    return ("Replicate pricing is model/hardware-specific (billed by predict time); "
            "cost_usd is not estimated by this factory.")


def _replicate_run_impl(project: str, model: str, input: dict, wait_seconds: "int | None" = None,
                        *, settings, replicate=replicate_mod) -> dict:
    """Клон _fal_run_impl: все отказы (project/model/input/токен) — до media/ и до сети."""
    base = {"backend": "replicate", "model": model, "cost_usd": None,
            "pricing_note": _replicate_pricing_note()}
    try:
        media.require_absolute_project(project)
    except ValueError as e:
        return {"error": str(e), "status": "error", **base}
    try:
        replicate.validate_model(model)
        if not isinstance(input, dict):
            raise replicate.ReplicateError("Replicate input must be a JSON object")
    except replicate.ReplicateError as e:
        return {"error": str(e), "status": "error", **base}
    if not settings.replicate_token:
        return {"error": "Missing REPLICATE_API_TOKEN. Set REPLICATE_API_TOKEN in .env to use "
                         "Replicate.", "status": "error", **base}
    wait_budget = settings.replicate_timeout if wait_seconds is None else int(wait_seconds)
    out_dir = media.generated_dir(Path(project), media.today())
    try:
        res = replicate.run(model, input, api_key=settings.replicate_token,
                            api_url=settings.replicate_base_url,
                            timeout=settings.replicate_timeout, wait_seconds=wait_budget,
                            poll_interval=settings.replicate_poll_interval,
                            download_timeout=settings.replicate_download_timeout,
                            out_dir=out_dir)
    except replicate.ReplicateError as e:
        return {"error": str(e), "status": "error", **base}
    out = {**base, "status": res.get("status"), "id": res.get("id")}
    if res.get("status") == "pending":
        out["poll_url"] = res.get("poll_url")
        return out
    out.update({"outputs": res.get("output_urls", []), "raw_output": res.get("output"),
                "media": res.get("media", {}), "media_urls": res.get("media_urls", [])})
    if res.get("metrics"):
        out["metrics"] = res["metrics"]
    if res.get("warnings"):
        out["warnings"] = res["warnings"]
    return out


def _higgsfield_pricing_note() -> str:
    return ("Higgsfield bills credits per model/operation; cost_usd is not estimated by this "
            "factory.")


def _higgsfield_run_impl(project: str, model: str, input: dict, wait_seconds: "int | None" = None,
                         *, settings, higgsfield=higgsfield_mod) -> dict:
    """Клон _replicate_run_impl: все отказы (project/model/input/ключ) — до media/ и до сети."""
    base = {"backend": "higgsfield", "model": model, "cost_usd": None,
            "pricing_note": _higgsfield_pricing_note()}
    try:
        media.require_absolute_project(project)
    except ValueError as e:
        return {"error": str(e), "status": "error", **base}
    try:
        higgsfield.validate_model(model)
        if not isinstance(input, dict):
            raise higgsfield.HiggsfieldError("Higgsfield input must be a JSON object")
    except higgsfield.HiggsfieldError as e:
        return {"error": str(e), "status": "error", **base}
    if not settings.higgsfield_api_key_id or not settings.higgsfield_api_key_secret:
        return {"error": "Missing HIGGSFIELD_API_KEY_ID/SECRET. Set both HIGGSFIELD_API_KEY_ID "
                         "and HIGGSFIELD_API_KEY_SECRET in .env to use Higgsfield.",
                "status": "error", **base}
    wait_budget = settings.higgsfield_timeout if wait_seconds is None else int(wait_seconds)
    out_dir = media.generated_dir(Path(project), media.today())
    try:
        res = higgsfield.run(model, input, api_key_id=settings.higgsfield_api_key_id,
                             api_key_secret=settings.higgsfield_api_key_secret,
                             base_url=settings.higgsfield_base_url,
                             timeout=settings.higgsfield_timeout, wait_seconds=wait_budget,
                             poll_interval=settings.higgsfield_poll_interval,
                             download_timeout=settings.higgsfield_download_timeout,
                             out_dir=out_dir)
    except higgsfield.HiggsfieldError as e:
        return {"error": str(e), "status": "error", **base}
    out = {**base, "status": res.get("status"), "id": res.get("id")}
    if res.get("status") == "pending":
        out["poll_url"] = res.get("poll_url")
        return out
    out.update({"outputs": res.get("output_urls", []), "raw_output": res.get("output"),
                "media": res.get("media", {}), "media_urls": res.get("media_urls", [])})
    if res.get("warnings"):
        out["warnings"] = res["warnings"]
    return out


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
                          raw: bool = False, backend: str = "") -> dict:
        """Сгенерировать видео. mode: i2v|t2v|frames|multimodal. project — АБСОЛЮТНЫЙ путь.
        backend: ""(авто по model) | dreamina (Seedance) | magnific (REST: model=veo-3-1 | kling-v2-5-pro).
        Пустой backend + magnific-модель (kling-*/veo-*) → авто-Magnific; иначе Dreamina.
        Dreamina при ExceedConcurrencyLimit (ret=1310) авто-фолбэчится на Magnific (i2v→kling, t2v→veo),
        флаг fallback="magnific" в ответе. prompt = задача (райтер перепишет); raw=True — дословно.
        i2v magnific: image = http-URL кадра (или локальный winner → base64). Возвращает
        status/output/prompt_used/task_id + credits(dreamina) или cost_usd(magnific) + warning/fallback."""
        return _generate_video_impl(project, mode, prompt, image, first, last, images, video,
                                    audio, model, duration, ratio, resolution, raw, backend,
                                    settings=settings)

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

    @mcp.tool()
    def gf_fal_run(project: str, endpoint: str, input: dict,
                   wait_seconds: "int | None" = None) -> dict:
        """Run any fal.ai model or authenticated workflow endpoint through the queue API.
        project must be an absolute path. Local file inputs are explicit markers:
        @C:/path/file.png or @R:/path/file.png. A marker inside video_urls/image_urls/audio_urls
        is uploaded to fal storage and replaced by its https URL (those fields reject data URIs,
        e.g. Seedance reference-to-video); elsewhere a marker becomes a base64 data URI.
        Cost is not estimated because fal pricing is endpoint-specific."""
        return _fal_run_impl(project, endpoint, input, wait_seconds, settings=settings)

    @mcp.tool()
    def gf_fal_list_workflows(search: str = "", used_endpoint_ids: str = "",
                              limit: int = 50, cursor: str = "") -> dict:
        """List authenticated user's fal.ai workflows. Requires FAL_KEY."""
        return _fal_list_workflows_impl(search, used_endpoint_ids, limit, cursor,
                                        settings=settings)

    @mcp.tool()
    def gf_replicate_run(project: str, model: str, input: dict,
                         wait_seconds: "int | None" = None) -> dict:
        """Run any Replicate model through the predictions API. project must be an absolute path.
        model: owner/name (official/latest) | owner/name:<64-hex version> | <64-hex version>.
        Local file inputs are explicit markers anywhere in input (@C:/path/file.png, @R:/...):
        each is uploaded via the Replicate Files API and replaced by its URL. Output media are
        downloaded to media/generated/<date>/ (video/audio -> video/). Not finished within
        wait_seconds -> status=pending + id/poll_url. Cost is not estimated (model/hardware-specific)."""
        return _replicate_run_impl(project, model, input, wait_seconds, settings=settings)

    @mcp.tool()
    def gf_higgsfield_run(project: str, model: str, input: dict,
                          wait_seconds: "int | None" = None) -> dict:
        """Run any Higgsfield model (image or video). project must be an absolute path.
        model: the API model path, e.g. veo3.1 | nano-banana | higgsfield-ai/soul/standard |
        bytedance/seedance/v1/lite/image-to-video. input is the request body itself (flat, no
        wrapper); most models require prompt, image-to-video also image_url.
        Local file inputs are explicit markers anywhere in input (@C:/path/file.png, @R:/...):
        each is uploaded via a presigned URL and replaced by its public URL. Output media are
        downloaded to media/generated/<date>/ (video/audio -> video/). Not finished within
        wait_seconds -> status=pending + id/poll_url. Cost is not estimated (credit-based)."""
        return _higgsfield_run_impl(project, model, input, wait_seconds, settings=settings)

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
