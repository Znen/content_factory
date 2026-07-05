import pytest
from gf import naming


def test_parse_set_id_ok():
    assert naming.parse_set_id("cast/kurtukova") == ("cast", "kurtukova")
    assert naming.parse_set_id("lineart/shot-02") == ("lineart", "shot-02")


@pytest.mark.parametrize("bad", ["cast", "cast/", "/x", "nope/x",
                                 "cast/UPPER", "cast/a/b", "lineart/-x"])
def test_parse_set_id_rejects(bad):
    with pytest.raises(naming.NamingError):
        naming.parse_set_id(bad)


def test_set_home_reference(tmp_path):
    assert naming.set_home(tmp_path, "cast", "kurtukova") == \
        tmp_path / "references" / "cast" / "kurtukova"


def test_set_home_generated_uses_explicit_date(tmp_path):
    assert naming.set_home(tmp_path, "lineart", "shot-02", date="2026-07-05") == \
        tmp_path / "generated" / "2026-07-05" / "shot-02"


def test_history_dirs_span_dates(tmp_path):
    for d in ["2026-07-04", "2026-07-05"]:
        (tmp_path / "generated" / d / "shot-02").mkdir(parents=True)
    (tmp_path / "generated" / "storyboard").mkdir()  # non-date dir without the set
    dirs = naming.set_history_dirs(tmp_path, "lineart", "shot-02")
    assert [d.parent.name for d in dirs] == ["2026-07-04", "2026-07-05"]


def test_next_index_union_of_scan_and_ledger(tmp_path):
    (tmp_path / "generated" / "2026-07-04" / "shot-02").mkdir(parents=True)
    (tmp_path / "generated" / "2026-07-05" / "shot-02").mkdir(parents=True)
    (tmp_path / "generated" / "2026-07-04" / "shot-02" / "lineart-v1.png").write_bytes(b"x")
    (tmp_path / "generated" / "2026-07-05" / "shot-02" / "lineart-v3.png").write_bytes(b"x")
    ledger = [{"op": "add_variant", "set_id": "lineart/shot-02",
               "path": "generated/2026-07-03/shot-02/lineart-v7.png"}]
    assert naming.next_index(tmp_path, "lineart", "shot-02", "lineart",
                             ledger, "lineart/shot-02") == 8


def test_next_index_reference_ignores_unrelated(tmp_path):
    d = tmp_path / "references" / "cast" / "kurtukova"
    d.mkdir(parents=True)
    (d / "kurtukova-05.jpg").write_bytes(b"x")
    (d / "unrelated.png").write_bytes(b"x")
    assert naming.next_index(tmp_path, "cast", "kurtukova", "kurtukova",
                             [], "cast/kurtukova") == 6


def test_canonical_names():
    assert naming.canonical_name("cast", "kurtukova", 7, ".jpg") == "kurtukova-07.jpg"
    assert naming.canonical_name("final", "magnific", 6, ".PNG") == "magnific-v6.png"


def test_variant_stem():
    assert naming.variant_stem("lineart", "shot-02") == "lineart"
    assert naming.variant_stem("final", "shot-02", stage="magnific") == "magnific"
    assert naming.variant_stem("cast", "kurtukova") == "kurtukova"


def test_stems_for_set_includes_ledger_stages():
    ledger = [{"op": "add_variant", "set_id": "final/shot-02",
               "path": "generated/2026-07-05/shot-02/magnific-v1.png",
               "stage": "magnific"}]
    assert naming.stems_for_set("final", ledger, "final/shot-02") == \
        {"final", "magnific"}
