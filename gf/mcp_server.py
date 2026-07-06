"""generation-factory MCP server: gf_generate_draft (ComfyUI) + gf_generate_final (Nano)."""

from __future__ import annotations

from pathlib import Path

from . import pricing, budget as budget_mod, media, writer as writer_mod
from .backends import nano as nano_mod, comfyui as comfyui_mod


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
