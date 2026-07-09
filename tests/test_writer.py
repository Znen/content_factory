import json
from pathlib import Path

import pytest

from gf import writer
from gf.config import Settings

PASSPORT = """---
target: comfyui/sdxl-test
platform: comfyui
syntax: tags
negative: true
refs: none
updated: 2026-07-06
---
# Как писать промпт
Тело гайда.
"""


def _docs(tmp_path) -> Path:
    root = tmp_path / "promptdocs"
    (root / "comfyui").mkdir(parents=True)
    (root / "comfyui" / "sdxl-test.md").write_text(PASSPORT, encoding="utf-8")
    return root


def test_load_passport_ok(tmp_path):
    p = writer.load_passport("comfyui/sdxl-test", root=_docs(tmp_path))
    assert p["meta"]["platform"] == "comfyui"
    assert "Тело гайда" in p["body"]


def test_load_passport_unknown_target_lists_available(tmp_path):
    with pytest.raises(writer.WriterError) as e:
        writer.load_passport("magnific/nope", root=_docs(tmp_path))
    assert "comfyui/sdxl-test" in str(e.value)


def test_load_passport_broken_frontmatter(tmp_path):
    root = _docs(tmp_path)
    (root / "comfyui" / "bad.md").write_text("no frontmatter here", encoding="utf-8")
    with pytest.raises(writer.WriterError) as e:
        writer.load_passport("comfyui/bad", root=root)
    assert "bad.md" in str(e.value)


def test_list_targets_skips_catalog_files(tmp_path):
    root = _docs(tmp_path)
    (root / "magnific").mkdir()
    (root / "magnific" / "_catalog.md").write_text("справочник", encoding="utf-8")
    targets = writer.list_targets(root=root)
    assert [t["target"] for t in targets] == ["comfyui/sdxl-test"]


def test_real_promptdocs_have_valid_frontmatter():
    """Каждый настоящий паспорт в gf/promptdocs валиден (Ф-П1 quality gate)."""
    if not writer.PROMPTDOCS.exists():
        pytest.skip("promptdocs ещё не созданы")
    targets = writer.list_targets()
    for t in targets:
        assert t["target"], t
    # gf_list_targets/CLI echo json.dumps() результат напрямую — регрессия на
    # неквотированный `updated: YYYY-MM-DD` (YAML -> datetime.date, не сериализуется).
    json.dumps({"targets": targets})


def test_list_targets_updated_is_json_safe_string(tmp_path):
    targets = writer.list_targets(root=_docs(tmp_path))
    assert targets[0]["updated"] == "2026-07-06"
    json.dumps(targets)


def _settings(enabled=True):
    return Settings(
        comfyui_url="http://127.0.0.1:8188", comfyui_ckpt="m.safetensors",
        comfyui_workflow="", nano_server_url="http://localhost:3001", nano_env_file="",
        nano_timeout=120, image_cap_usd=None, mcp_bind="127.0.0.1", mcp_port=8766,
        mcp_token=None, writer_model="claude-sonnet-5", writer_max_tokens=2000,
        writer_enabled=enabled, writer_draft_target="comfyui/sdxl-test",
        writer_final_target="nano/gemini-image", dreamina_bin="dreamina",
        dreamina_poll_wait=180, dreamina_default_model="seedance2.0fast")


class _Block:
    type = "tool_use"

    def __init__(self, payload):
        self.input = payload


class _Usage:
    input_tokens = 1000
    output_tokens = 200


class _Resp:
    def __init__(self, payload):
        self.content = [_Block(payload)]
        self.usage = _Usage()


class _FakeClient:
    def __init__(self, payloads):
        self.calls = []
        self._payloads = list(payloads)

        outer = self

        class _Messages:
            def create(self, **kw):
                outer.calls.append(kw)
                return _Resp(outer._payloads.pop(0))

        self.messages = _Messages()


GOOD = {"prompt": "cinematic photo, rain", "negative": "blurry",
        "params": {"steps": 30}, "notes": "ok"}


def test_write_prompt_happy_path(tmp_path):
    root = _docs(tmp_path)
    fake = _FakeClient([GOOD])
    out = writer.write_prompt(str(tmp_path), "comfyui/sdxl-test", "Кадр 1: дождь",
                              settings=_settings(), client=fake, root=root)
    assert out["prompt"] == "cinematic photo, rain"
    assert out["negative"] == "blurry"
    assert out["target"] == "comfyui/sdxl-test"
    # системный промпт содержит тело паспорта, user — задачу
    kw = fake.calls[0]
    assert "Тело гайда" in kw["system"]
    assert "Кадр 1: дождь" in kw["messages"][0]["content"]
    assert kw["tool_choice"] == {"type": "tool", "name": "emit_prompt"}
    assert "temperature" not in kw and "thinking" not in kw


def test_write_prompt_includes_style_and_refs(tmp_path):
    root = _docs(tmp_path)
    style = tmp_path / "prompts"
    style.mkdir()
    (style / "style.md").write_text("тёплая плёнка", encoding="utf-8")
    fake = _FakeClient([GOOD])
    writer.write_prompt(str(tmp_path), "comfyui/sdxl-test", "задача",
                        refs=["cast/kurtukova/winner.png"], aspect="9:16",
                        extra="меньше тумана", settings=_settings(), client=fake, root=root)
    user = fake.calls[0]["messages"][0]["content"]
    assert "тёплая плёнка" in user
    assert "kurtukova" in user
    assert "9:16" in user and "меньше тумана" in user


def test_write_prompt_logs_to_prompts_dir_and_costs(tmp_path):
    root = _docs(tmp_path)
    out = writer.write_prompt(str(tmp_path), "comfyui/sdxl-test", "задача",
                              settings=_settings(), client=_FakeClient([GOOD]), root=root)
    log = Path(out["log_path"])
    assert log.exists() and log.parent == tmp_path / "prompts"
    assert log.name.endswith("-sdxl-test-01.md")
    assert "cinematic photo, rain" in log.read_text(encoding="utf-8")
    # стоимость из usage попала в бюджет-лог
    cost_log = (tmp_path / "media" / ".gf_cost_log.jsonl").read_text(encoding="utf-8")
    rec = json.loads(cost_log.strip().splitlines()[-1])
    assert rec["backend"] == "writer" and rec["cost_usd"] > 0


def test_write_prompt_log_numbering_continues(tmp_path):
    root = _docs(tmp_path)
    writer.write_prompt(str(tmp_path), "comfyui/sdxl-test", "a",
                        settings=_settings(), client=_FakeClient([GOOD]), root=root)
    out2 = writer.write_prompt(str(tmp_path), "comfyui/sdxl-test", "b",
                               settings=_settings(), client=_FakeClient([GOOD]), root=root)
    assert out2["log_path"].endswith("-sdxl-test-02.md")


def test_write_prompt_retries_once_on_bad_schema(tmp_path):
    root = _docs(tmp_path)
    fake = _FakeClient([{"nope": 1}, GOOD])  # первый ответ без prompt
    out = writer.write_prompt(str(tmp_path), "comfyui/sdxl-test", "задача",
                              settings=_settings(), client=fake, root=root)
    assert out["prompt"] == "cinematic photo, rain"
    assert len(fake.calls) == 2
    # стоимость — СУММА обоих оплаченных вызовов: 2 x (1000 in / 200 out)
    from gf import pricing
    cost_log = (tmp_path / "media" / ".gf_cost_log.jsonl").read_text(encoding="utf-8")
    rec = json.loads(cost_log.strip().splitlines()[-1])
    assert rec["cost_usd"] == pricing.estimate_llm("claude-sonnet-5", 2000, 400)


def test_write_prompt_fails_after_two_bad_schemas(tmp_path):
    root = _docs(tmp_path)
    with pytest.raises(writer.WriterError):
        writer.write_prompt(str(tmp_path), "comfyui/sdxl-test", "задача",
                            settings=_settings(),
                            client=_FakeClient([{"nope": 1}, {"nope": 2}]), root=root)


def test_write_prompt_no_key_raises_clean_writer_error(tmp_path):
    """Anthropic SDK валидирует auth-заголовки лениво: без ANTHROPIC_API_KEY
    `messages.create()` кидает голый TypeError (не APIError). Должен дойти до
    вызывающего как чистый WriterError, а не как traceback (fail-closed)."""
    root = _docs(tmp_path)

    class _NoKeyClient:
        class messages:
            @staticmethod
            def create(**kw):
                raise TypeError(
                    '"Could not resolve authentication method. Expected one of '
                    'api_key, auth_token, or credentials to be set."'
                )

    with pytest.raises(writer.WriterError, match="клиент/ключ"):
        writer.write_prompt(str(tmp_path), "comfyui/sdxl-test", "задача",
                            settings=_settings(), client=_NoKeyClient(), root=root)


def test_write_prompt_failure_still_logs_cost(tmp_path):
    root = _docs(tmp_path)
    with pytest.raises(writer.WriterError):
        writer.write_prompt(str(tmp_path), "comfyui/sdxl-test", "задача",
                            settings=_settings(),
                            client=_FakeClient([{"nope": 1}, {"nope": 2}]), root=root)
    # оба вызова оплачены — стоимость логируется даже при отказе
    cost_log = (tmp_path / "media" / ".gf_cost_log.jsonl").read_text(encoding="utf-8")
    rec = json.loads(cost_log.strip().splitlines()[-1])
    assert rec["backend"] == "writer" and rec["cost_usd"] > 0


def test_write_prompt_cost_log_failure_does_not_crash(tmp_path):
    """budget.log_cost делает mkdir+append — на read-only диске/правах может
    бросить OSError. Потеря записи о стоимости приемлема, падение всего
    write_prompt (и, транзитивно, gf_generate_*) — нет."""
    root = _docs(tmp_path)

    class _BrokenBudget:
        @staticmethod
        def log_cost(*a, **kw):
            raise OSError("read-only filesystem")

    out = writer.write_prompt(str(tmp_path), "comfyui/sdxl-test", "задача",
                              settings=_settings(), client=_FakeClient([GOOD]),
                              root=root, budget=_BrokenBudget())
    assert out["prompt"] == "cinematic photo, rain"


def test_write_prompt_disabled_raises(tmp_path):
    with pytest.raises(writer.WriterError) as e:
        writer.write_prompt(str(tmp_path), "comfyui/sdxl-test", "задача",
                            settings=_settings(enabled=False),
                            client=_FakeClient([GOOD]), root=_docs(tmp_path))
    assert "GF_WRITER_ENABLED" in str(e.value)


def test_estimate_llm_pricing():
    from gf import pricing
    # sonnet-5: $3/M in + $15/M out
    assert pricing.estimate_llm("claude-sonnet-5", 1_000_000, 0) == 3.0
    assert pricing.estimate_llm("claude-sonnet-5", 0, 1_000_000) == 15.0
    assert pricing.estimate_llm("unknown-model", 1_000_000, 0) == 5.0  # дефолт
