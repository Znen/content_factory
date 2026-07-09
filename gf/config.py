import os
from dataclasses import dataclass


@dataclass
class Settings:
    comfyui_url: str
    comfyui_ckpt: str
    comfyui_workflow: str
    nano_server_url: str
    nano_env_file: str
    nano_timeout: int
    image_cap_usd: "float | None"
    mcp_bind: str
    mcp_port: int
    mcp_token: "str | None"
    writer_model: str
    writer_max_tokens: int
    writer_enabled: bool
    writer_draft_target: str
    writer_final_target: str
    dreamina_bin: str
    dreamina_poll_wait: int
    dreamina_default_model: str
    magnific_api_key: "str | None"
    magnific_base_url: str
    magnific_timeout: int
    magnific_poll_interval: int
    magnific_download_timeout: int
    magnific_download_retries: int


def _float_or_none(raw: str) -> "float | None":
    raw = (raw or "").strip()
    return float(raw) if raw else None


def _bool(raw: str, default: bool) -> bool:
    raw = (raw or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def load_settings() -> Settings:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    return Settings(
        comfyui_url=os.environ.get("GF_COMFYUI_URL", "http://127.0.0.1:8188"),
        comfyui_ckpt=os.environ.get("GF_COMFYUI_CKPT", "juggernautxl_ragnarok.safetensors"),
        comfyui_workflow=os.environ.get("GF_COMFYUI_WORKFLOW", ""),
        nano_server_url=os.environ.get("GF_NANO_SERVER_URL", "http://localhost:3001"),
        nano_env_file=os.environ.get("GF_NANO_ENV_FILE", ""),
        nano_timeout=int(os.environ.get("GF_NANO_TIMEOUT", "120")),
        image_cap_usd=_float_or_none(os.environ.get("GF_IMAGE_CAP_USD", "")),
        mcp_bind=os.environ.get("GF_MCP_BIND", "127.0.0.1"),
        mcp_port=int(os.environ.get("GF_MCP_PORT", "8766")),
        mcp_token=os.environ.get("GF_MCP_TOKEN") or None,
        writer_model=os.environ.get("GF_WRITER_MODEL", "claude-sonnet-5"),
        writer_max_tokens=int(os.environ.get("GF_WRITER_MAX_TOKENS", "2000")),
        writer_enabled=_bool(os.environ.get("GF_WRITER_ENABLED", ""), True),
        writer_draft_target=os.environ.get("GF_WRITER_DRAFT_TARGET", "comfyui/sdxl-juggernaut"),
        writer_final_target=os.environ.get("GF_WRITER_FINAL_TARGET", "nano/gemini-image"),
        dreamina_bin=os.environ.get("GF_DREAMINA_BIN", "dreamina"),
        dreamina_poll_wait=int(os.environ.get("GF_DREAMINA_POLL_WAIT", "180")),
        dreamina_default_model=os.environ.get("GF_DREAMINA_MODEL", "seedance2.0fast"),
        magnific_api_key=os.environ.get("GF_MAGNIFIC_API_KEY") or None,
        magnific_base_url=os.environ.get("GF_MAGNIFIC_BASE_URL", "https://api.magnific.com"),
        magnific_timeout=int(os.environ.get("GF_MAGNIFIC_TIMEOUT", "180")),
        magnific_poll_interval=int(os.environ.get("GF_MAGNIFIC_POLL_INTERVAL", "3")),
        magnific_download_timeout=int(os.environ.get("GF_MAGNIFIC_DOWNLOAD_TIMEOUT", "120")),
        magnific_download_retries=int(os.environ.get("GF_MAGNIFIC_DOWNLOAD_RETRIES", "3")),
    )
