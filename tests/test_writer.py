from pathlib import Path

import pytest

from gf import writer

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
    for t in writer.list_targets():
        assert t["target"], t
