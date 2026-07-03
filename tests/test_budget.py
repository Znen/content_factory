from pathlib import Path
from gf.budget import log_cost, spent, check


def test_spent_empty(tmp_path):
    assert spent(tmp_path) == 0.0


def test_log_and_sum(tmp_path):
    log_cost(tmp_path, "nano", 2, 0.08, note="shot-01")
    log_cost(tmp_path, "nano", 1, 0.04)
    assert round(spent(tmp_path), 4) == 0.12
    logfile = tmp_path / "media" / ".gf_cost_log.jsonl"
    assert logfile.exists()
    assert len(logfile.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_check_no_cap_allows(tmp_path):
    out = check(tmp_path, 100.0, None)
    assert out["allowed"] is True
    assert out["cap"] is None


def test_check_cap_blocks_over(tmp_path):
    log_cost(tmp_path, "nano", 1, 4.0)
    out = check(tmp_path, 1.5, cap_usd=5.0)
    assert out["allowed"] is False
    assert out["spent"] == 4.0
    assert "cap" in out["reason"].lower()


def test_check_cap_allows_under(tmp_path):
    log_cost(tmp_path, "nano", 1, 1.0)
    out = check(tmp_path, 1.0, cap_usd=5.0)
    assert out["allowed"] is True
