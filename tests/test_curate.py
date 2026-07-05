from pathlib import Path
import pytest
from gf import curate
from gf.curate_state import load_manifest, read_ledger


def _proj(tmp_path):
    (tmp_path / "media").mkdir(exist_ok=True)
    return tmp_path


def _img(dir_: Path, name="src.png", data=b"PNGDATA"):
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / name
    p.write_bytes(data)
    return p


def test_add_variant_reference_copies_renames_ledgers(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "incoming", "IMG_4211.jpg", b"JPGDATA")
    out = curate.add_variant(str(proj), str(src), "cast/kurtukova", note="из брифа")
    assert "error" not in out
    assert out["path"] == "references/cast/kurtukova/kurtukova-01.jpg"
    assert (proj / "media" / out["path"]).read_bytes() == b"JPGDATA"
    assert src.exists()  # source untouched
    rec = read_ledger(proj)[-1]
    assert rec["op"] == "add_variant" and rec["original_name"] == "IMG_4211.jpg"
    assert rec["note"] == "из брифа" and rec["sha256"] == out["sha256"]


def test_add_variant_generated_uses_date_and_stage(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "x.png")
    out = curate.add_variant(str(proj), str(src), "final/shot-02",
                             date="2026-07-05", stage="magnific")
    assert out["path"] == "generated/2026-07-05/shot-02/magnific-v1.png"
    assert read_ledger(proj)[-1]["stage"] == "magnific"


def test_add_variant_numbering_continues_across_calls(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png")
    curate.add_variant(str(proj), str(src), "lineart/shot-01", date="2026-07-05")
    out2 = curate.add_variant(str(proj), str(src), "lineart/shot-01", date="2026-07-05")
    assert out2["path"].endswith("/lineart-v2.png")


def test_add_variant_hash_mismatch_keeps_source_removes_copy(tmp_path, monkeypatch):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png")
    hashes = iter(["aaa", "bbb"])
    monkeypatch.setattr(curate, "_sha256", lambda p: next(hashes))
    out = curate.add_variant(str(proj), str(src), "cast/anna")
    assert "error" in out and "copy failed" in out["error"].lower()
    assert src.exists()
    home = proj / "media" / "references" / "cast" / "anna"
    assert not home.exists() or not any(home.iterdir())


def test_add_variant_validation_errors(tmp_path):
    proj = _proj(tmp_path)
    gif = _img(tmp_path / "in", "a.gif", b"GIF")
    assert "error" in curate.add_variant(str(proj), str(gif), "cast/anna")
    png = _img(tmp_path / "in", "b.png")
    assert "error" in curate.add_variant(str(proj), str(png), "wat/anna")
    assert "error" in curate.add_variant(str(proj), str(png), "cast/anna", stage="x")
    assert "error" in curate.add_variant(str(proj), str(tmp_path / "nope.png"), "cast/anna")


def test_add_variant_io_error_contained_no_leftover(tmp_path, monkeypatch):
    import shutil as _sh
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png")

    def _boom(s, d):
        from pathlib import Path as _P
        _P(d).write_bytes(b"partial")   # simulate partial write
        raise OSError("disk full")

    monkeypatch.setattr(curate.shutil, "copy2", _boom)
    out = curate.add_variant(str(proj), str(src), "cast/anna")
    assert "error" in out and "copy failed" in out["error"].lower()
    assert src.exists()
    home = proj / "media" / "references" / "cast" / "anna"
    assert not home.exists() or not any(home.iterdir())  # partial cleaned up
