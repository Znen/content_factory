import pytest

from gf.config import load_settings


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch):
    """Keep config tests hermetic: a real .env must not leak into asserts."""
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: None)


def test_defaults(monkeypatch):
    for k in list(__import__("os").environ):
        if k.startswith("GF_"):
            monkeypatch.delenv(k, raising=False)
    s = load_settings()
    assert s.comfyui_url == "http://127.0.0.1:8188"
    assert s.comfyui_ckpt.endswith(".safetensors")
    assert s.nano_server_url == "http://localhost:3001"
    assert s.nano_timeout == 120
    assert s.image_cap_usd is None
    assert s.mcp_bind == "127.0.0.1"
    assert s.mcp_port == 8766
    assert s.mcp_token is None


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("GF_MCP_PORT", "9000")
    monkeypatch.setenv("GF_MCP_TOKEN", "secret")
    monkeypatch.setenv("GF_IMAGE_CAP_USD", "5.5")
    s = load_settings()
    assert s.mcp_port == 9000
    assert s.mcp_token == "secret"
    assert s.image_cap_usd == 5.5


def test_writer_settings_defaults(monkeypatch):
    for var in ("GF_WRITER_MODEL", "GF_WRITER_MAX_TOKENS", "GF_WRITER_ENABLED",
                "GF_WRITER_DRAFT_TARGET", "GF_WRITER_FINAL_TARGET"):
        monkeypatch.delenv(var, raising=False)
    from gf.config import load_settings
    s = load_settings()
    assert s.writer_model == "claude-sonnet-5"
    assert s.writer_max_tokens == 2000
    assert s.writer_enabled is True
    assert s.writer_draft_target == "comfyui/sdxl-juggernaut"
    assert s.writer_final_target == "nano/gemini-image"


def test_writer_settings_overrides(monkeypatch):
    monkeypatch.setenv("GF_WRITER_MODEL", "claude-haiku-4-5")
    monkeypatch.setenv("GF_WRITER_ENABLED", "false")
    from gf.config import load_settings
    s = load_settings()
    assert s.writer_model == "claude-haiku-4-5"
    assert s.writer_enabled is False


def test_dreamina_settings_defaults(monkeypatch):
    for var in ("GF_DREAMINA_BIN", "GF_DREAMINA_POLL_WAIT", "GF_DREAMINA_MODEL"):
        monkeypatch.delenv(var, raising=False)
    from gf.config import load_settings
    s = load_settings()
    assert s.dreamina_bin == "dreamina"
    assert s.dreamina_poll_wait == 180
    assert s.dreamina_default_model == "seedance2.0fast"


def test_dreamina_settings_overrides(monkeypatch):
    monkeypatch.setenv("GF_DREAMINA_BIN", "/opt/dreamina")
    monkeypatch.setenv("GF_DREAMINA_POLL_WAIT", "60")
    monkeypatch.setenv("GF_DREAMINA_MODEL", "seedance2.0_vip")
    from gf.config import load_settings
    s = load_settings()
    assert s.dreamina_bin == "/opt/dreamina"
    assert s.dreamina_poll_wait == 60
    assert s.dreamina_default_model == "seedance2.0_vip"


def test_magnific_settings_defaults(monkeypatch):
    for var in ("GF_MAGNIFIC_API_KEY", "GF_MAGNIFIC_BASE_URL",
                "GF_MAGNIFIC_TIMEOUT", "GF_MAGNIFIC_POLL_INTERVAL"):
        monkeypatch.delenv(var, raising=False)
    from gf.config import load_settings
    s = load_settings()
    assert s.magnific_api_key is None
    assert s.magnific_base_url == "https://api.magnific.com"
    assert s.magnific_timeout == 180
    assert s.magnific_poll_interval == 3


def test_magnific_settings_overrides(monkeypatch):
    monkeypatch.setenv("GF_MAGNIFIC_API_KEY", "mk-123")
    monkeypatch.setenv("GF_MAGNIFIC_TIMEOUT", "90")
    from gf.config import load_settings
    s = load_settings()
    assert s.magnific_api_key == "mk-123"
    assert s.magnific_timeout == 90
