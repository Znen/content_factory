"""generation-factory MCP server: gf_generate_draft (ComfyUI) + gf_generate_final (Nano)."""

from __future__ import annotations

from pathlib import Path

from . import pricing, budget as budget_mod, media
from .backends import nano as nano_mod, comfyui as comfyui_mod


def _generate_draft_impl(project: str, prompt: str, n: int = 4, negative: str = "",
                         seed: int = 0, *, settings, comfy=comfyui_mod, budget=budget_mod) -> dict:
    project_dir = Path(project)
    date = media.today()
    out_dir = media.drafts_dir(project_dir, date)
    cost = pricing.estimate("comfyui", n)  # 0.0 for local
    gate = budget.check(project_dir, cost, settings.image_cap_usd)
    if not gate["allowed"]:
        return {"error": gate["reason"], "images": [], "backend": "comfyui",
                "cost_usd": cost, "spent_usd": gate["spent"]}
    saved = comfy.generate(prompt, out_dir, server_url=settings.comfyui_url,
                           ckpt=settings.comfyui_ckpt, workflow_path=settings.comfyui_workflow or None,
                           n=n, negative=negative, seed=seed)
    budget.log_cost(project_dir, "comfyui", n, cost, note=f"draft {date}")
    return {"images": [str(p) for p in saved], "backend": "comfyui",
            "cost_usd": cost, "spent_usd": budget.spent(project_dir)}


def _generate_final_impl(project: str, prompt: str, refs: "list | None" = None, aspect: str = "9:16",
                         *, settings, nano=nano_mod, budget=budget_mod) -> dict:
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
    saved = nano.generate(prompt, refs, out_dir, server_url=settings.nano_server_url,
                          password=password, timeout=settings.nano_timeout, aspect=aspect)
    budget.log_cost(project_dir, "nano", 1, cost, note=f"final {date}")
    return {"images": [str(p) for p in saved], "backend": "nano",
            "cost_usd": cost, "spent_usd": budget.spent(project_dir)}


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
                          negative: str = "", seed: int = 0) -> dict:
        """Generate N cheap ComfyUI drafts into <project>/media/generated/<date>/_drafts/."""
        return _generate_draft_impl(project, prompt, n, negative, seed, settings=settings)

    @mcp.tool()
    def gf_generate_final(project: str, prompt: str, refs: "list | None" = None,
                          aspect: str = "9:16") -> dict:
        """Generate a client-facing final with Nano Banana (up to 4 multi-image refs)."""
        return _generate_final_impl(project, prompt, refs, aspect, settings=settings)

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
