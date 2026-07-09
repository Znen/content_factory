import pytest
from pathlib import Path

from gf.media import (drafts_dir, shot_dir, next_index, today, generated_dir,
                      require_absolute_project)


def test_drafts_dir_created(tmp_path):
    d = drafts_dir(tmp_path, "2026-07-03")
    assert d.exists()
    assert d.as_posix().endswith("media/generated/2026-07-03/_drafts")


def test_shot_dir_created(tmp_path):
    d = shot_dir(tmp_path, "2026-07-03", "shot-01")
    assert d.exists()
    assert d.as_posix().endswith("media/generated/2026-07-03/shot-01")


def test_next_index_counts(tmp_path):
    assert next_index(tmp_path, "draft") == 1
    (tmp_path / "draft-01.png").write_bytes(b"x")
    (tmp_path / "draft-02.png").write_bytes(b"x")
    assert next_index(tmp_path, "draft") == 3


def test_generated_dir_created(tmp_path):
    d = generated_dir(tmp_path, "2026-07-03")
    assert d.exists()
    assert d.as_posix().endswith("media/generated/2026-07-03")
    assert not (d / "_drafts").exists()  # no stray drafts folder


def test_today_format():
    s = today()
    assert len(s) == 10 and s[4] == "-" and s[7] == "-"


def test_require_absolute_project_ok(tmp_path):
    p = require_absolute_project(str(tmp_path))
    assert isinstance(p, Path) and p.is_absolute()


def test_require_absolute_project_rejects_relative():
    with pytest.raises(ValueError) as e:
        require_absolute_project("ingosstrakh")
    msg = str(e.value)
    assert "абсолют" in msg.lower() and "ingosstrakh" in msg
