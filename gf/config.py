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


def _float_or_none(raw: str) -> "float | None":
    raw = (raw or "").strip()
    return float(raw) if raw else None


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
    )
