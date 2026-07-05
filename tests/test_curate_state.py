import json
import pytest
from gf.curate_state import (CurateStateError, append_ledger, load_manifest,
                             read_ledger, save_manifest)


def test_load_manifest_default_when_missing(tmp_path):
    assert load_manifest(tmp_path) == {"version": 1, "winners": {}}


def test_save_load_roundtrip_atomic(tmp_path):
    m = {"version": 1, "winners": {"cast/kurtukova": {
        "path": "references/cast/kurtukova/kurtukova-05.jpg",
        "set_at": "2026-07-05T00:00:00+00:00", "history": []}}}
    save_manifest(tmp_path, m)
    assert load_manifest(tmp_path) == m
    assert not list((tmp_path / "media").glob("*.tmp"))  # no tmp litter


def test_corrupt_manifest_raises_with_recovery_hint(tmp_path):
    p = tmp_path / "media" / ".gf_winners.json"
    p.parent.mkdir(parents=True)
    p.write_text("{broken", encoding="utf-8")
    with pytest.raises(CurateStateError) as ei:
        load_manifest(tmp_path)
    assert "ledger" in str(ei.value).lower()


def test_malformed_manifest_shape_raises(tmp_path):
    p = tmp_path / "media" / ".gf_winners.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps([1, 2]), encoding="utf-8")
    with pytest.raises(CurateStateError):
        load_manifest(tmp_path)


def test_ledger_append_adds_ts_and_read_skips_garbage(tmp_path):
    append_ledger(tmp_path, {"op": "adopt", "set_id": "cast/a",
                             "dir": "references/cast/a", "files": 2})
    lp = tmp_path / "media" / ".gf_media_ledger.jsonl"
    with lp.open("a", encoding="utf-8") as fh:
        fh.write("not json\n123\n\n")
    recs = read_ledger(tmp_path)
    assert len(recs) == 1
    assert recs[0]["op"] == "adopt" and "ts" in recs[0]


def test_read_ledger_empty_when_missing(tmp_path):
    assert read_ledger(tmp_path) == []
