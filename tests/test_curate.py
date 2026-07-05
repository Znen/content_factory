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


def test_set_winner_updates_manifest_and_projection(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png")
    added = curate.add_variant(str(proj), str(src), "lineart/shot-01", date="2026-07-05")
    out = curate.set_winner(str(proj), "lineart/shot-01", added["path"])
    assert out["changed"] is True and out["prev"] is None
    m = load_manifest(proj)
    assert m["winners"]["lineart/shot-01"]["path"] == added["path"]
    assert (proj / "media" / "winners" / "lineart" / "shot-01.png").exists()
    assert read_ledger(proj)[-1]["op"] == "set_winner"


def test_set_winner_reassign_appends_history_and_is_idempotent(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png")
    v1 = curate.add_variant(str(proj), str(src), "lineart/shot-01", date="2026-07-05")
    v2 = curate.add_variant(str(proj), str(src), "lineart/shot-01", date="2026-07-05")
    curate.set_winner(str(proj), "lineart/shot-01", v1["path"])
    out = curate.set_winner(str(proj), "lineart/shot-01", v2["path"])
    assert out["prev"] == v1["path"]
    assert load_manifest(proj)["winners"]["lineart/shot-01"]["history"] == [v1["path"]]
    again = curate.set_winner(str(proj), "lineart/shot-01", v2["path"])
    assert again["changed"] is False


def test_set_winner_rejects_missing_or_outside(tmp_path):
    proj = _proj(tmp_path)
    assert "error" in curate.set_winner(str(proj), "lineart/shot-01", "generated/nope.png")
    outside = _img(tmp_path / "elsewhere", "x.png")
    assert "error" in curate.set_winner(str(proj), "lineart/shot-01", str(outside))


def test_materialize_rebuilds_and_cleans_stale(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png")
    added = curate.add_variant(str(proj), str(src), "cast/anna")
    curate.set_winner(str(proj), "cast/anna", added["path"])
    wdir = proj / "media" / "winners"
    (wdir / "cast" / "anna.png").unlink()          # проекцию испортили
    (wdir / "cast" / "stale.png").write_bytes(b"junk")
    out = curate.materialize_winners(str(proj))
    assert out["materialized"] == 1 and out["removed_stale"] == 1
    assert out["dangling"] == []
    assert (wdir / "cast" / "anna.png").exists()


def test_materialize_reports_dangling_winner(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png")
    added = curate.add_variant(str(proj), str(src), "cast/anna")
    curate.set_winner(str(proj), "cast/anna", added["path"])
    (proj / "media" / added["path"]).unlink()      # история потеряна извне
    out = curate.materialize_winners(str(proj))
    assert out["dangling"] == ["cast/anna"]


def test_set_winner_rejects_projection_and_purge_targets(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png")
    added = curate.add_variant(str(proj), str(src), "cast/anna")
    first = curate.set_winner(str(proj), "cast/anna", added["path"])
    assert first["changed"] is True
    # цель = проекция, которую вернул сам API — должно быть отвергнуто, манифест цел
    out = curate.set_winner(str(proj), "cast/anna", first["projection"])
    assert "error" in out
    m = load_manifest(proj)
    assert m["winners"]["cast/anna"]["path"] == added["path"]
    assert (proj / "media" / first["projection"]).exists()  # проекция не тронута


def test_set_winner_dotted_sibling_projection_preserved(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png")
    a1 = curate.add_variant(str(proj), str(src), "cast/anna")
    a2 = curate.add_variant(str(proj), str(src), "cast/anna.v2")
    curate.set_winner(str(proj), "cast/anna.v2", a2["path"])
    curate.set_winner(str(proj), "cast/anna", a1["path"])  # не должен снести anna.v2.png
    assert (proj / "media" / "winners" / "cast" / "anna.v2.png").exists()
    assert (proj / "media" / "winners" / "cast" / "anna.png").exists()


def test_set_winner_projection_failure_is_soft(tmp_path, monkeypatch):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png")
    added = curate.add_variant(str(proj), str(src), "cast/anna")

    def _boom(s, d):
        raise OSError("locked")

    monkeypatch.setattr(curate.shutil, "copy2", _boom)
    out = curate.set_winner(str(proj), "cast/anna", added["path"])
    assert "error" not in out and out["changed"] is True   # манифест = истина, обновлён
    assert "projection_error" in out
    m = load_manifest(proj)
    assert m["winners"]["cast/anna"]["path"] == added["path"]
    assert read_ledger(proj)[-1]["op"] == "set_winner"      # ledger в синхроне с манифестом


def test_adopt_registers_without_moving(tmp_path):
    proj = _proj(tmp_path)
    legacy = proj / "media" / "generated" / "2026-07-04" / "shot-03-kitchen"
    legacy.mkdir(parents=True)
    (legacy / "kitchen-birch-v1.jpg").write_bytes(b"x")
    (legacy / "kitchen-birch-v2.jpg").write_bytes(b"x")
    (legacy / "notes.txt").write_bytes(b"x")
    out = curate.adopt_set(str(proj), "final/shot-03-kitchen",
                           "generated/2026-07-04/shot-03-kitchen")
    assert out["files"] == 2                      # only images counted
    assert (legacy / "kitchen-birch-v1.jpg").exists()  # nothing moved
    assert read_ledger(proj)[-1]["op"] == "adopt"
    ids = [s["set_id"] for s in curate.list_sets(str(proj))["sets"]]
    assert "final/shot-03-kitchen" in ids


def test_adopt_rejects_outside_or_missing_dir(tmp_path):
    proj = _proj(tmp_path)
    assert "error" in curate.adopt_set(str(proj), "final/x", "generated/nope")
    assert "error" in curate.adopt_set(str(proj), "final/x", str(tmp_path / "elsewhere"))


def test_list_sets_discovers_reference_dirs_and_winner_flags(tmp_path):
    proj = _proj(tmp_path)
    d = proj / "media" / "references" / "cast" / "kurtukova"
    d.mkdir(parents=True)
    (d / "kurtukova-01.jpg").write_bytes(b"x")
    listed = curate.list_sets(str(proj), kind="cast")
    (s,) = listed["sets"]
    assert s["set_id"] == "cast/kurtukova"
    assert s["variants"] == 1 and s["winner"] is None
    curate.set_winner(str(proj), "cast/kurtukova",
                      "references/cast/kurtukova/kurtukova-01.jpg")
    listed = curate.list_sets(str(proj), kind="cast")
    assert listed["sets"][0]["winner_exists"] is True


def test_list_sets_counts_generated_by_stems(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png")
    curate.add_variant(str(proj), str(src), "final/shot-02",
                       date="2026-07-05", stage="magnific")
    curate.add_variant(str(proj), str(src), "final/shot-02", date="2026-07-05")
    curate.add_variant(str(proj), str(src), "lineart/shot-02", date="2026-07-05")
    sets = {s["set_id"]: s for s in curate.list_sets(str(proj))["sets"]}
    assert sets["final/shot-02"]["variants"] == 2      # magnific-v1 + final-v1
    assert sets["lineart/shot-02"]["variants"] == 1    # lineart-v1 only


def test_discard_moves_to_purge_verified(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png", b"KEEP")
    added = curate.add_variant(str(proj), str(src), "cast/anna")
    out = curate.discard(str(proj), added["path"])
    assert "error" not in out
    moved = proj / "media" / out["moved_to"]
    assert moved.read_bytes() == b"KEEP"
    assert out["moved_to"].startswith("_TO_PURGE/")
    assert not (proj / "media" / added["path"]).exists()
    assert read_ledger(proj)[-1]["op"] == "discard"


def test_discard_blocks_outside_media_and_double_discard(tmp_path):
    proj = _proj(tmp_path)
    outside = _img(tmp_path / "elsewhere", "x.png")
    assert "error" in curate.discard(str(proj), str(outside))
    src = _img(tmp_path / "in", "a.png")
    added = curate.add_variant(str(proj), str(src), "cast/anna")
    moved = curate.discard(str(proj), added["path"])["moved_to"]
    assert "error" in curate.discard(str(proj), moved)  # already in _TO_PURGE


def test_discard_current_winner_warns_dangling(tmp_path):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png")
    added = curate.add_variant(str(proj), str(src), "cast/anna")
    curate.set_winner(str(proj), "cast/anna", added["path"])
    out = curate.discard(str(proj), added["path"])
    assert "hint" in out and "cast/anna" in out["hint"]


def test_discard_unlink_failure_is_contained(tmp_path, monkeypatch):
    proj = _proj(tmp_path)
    src = _img(tmp_path / "in", "a.png")
    added = curate.add_variant(str(proj), str(src), "cast/anna")
    from pathlib import Path as _P
    real_unlink = _P.unlink

    def _locked(self, *a, **k):
        if self.suffix == ".png" and "_TO_PURGE" not in str(self):
            raise OSError("locked by another process")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(_P, "unlink", _locked)
    before = len(read_ledger(proj))
    out = curate.discard(str(proj), added["path"])
    assert "error" in out and "removing the source failed" in out["error"]
    assert (proj / "media" / added["path"]).exists()          # source intact
    assert len(read_ledger(proj)) == before                    # no ledger record
