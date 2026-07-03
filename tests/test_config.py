from gf.config import load_settings


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
