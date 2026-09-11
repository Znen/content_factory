import pytest
from typer.testing import CliRunner
from gf.cli import app

runner = CliRunner()


def test_help_lists_commands():
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    for c in ["version", "serve", "generate-draft", "generate-final"]:
        assert c in r.output


def test_version():
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0
    assert "0.1.0" in r.output


def test_help_lists_curation_commands():
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    for c in ["add-variant", "set-winner", "list-sets",
              "materialize-winners", "discard", "adopt-set"]:
        assert c in r.output


def test_help_lists_video_commands():
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    for c in ["generate-video", "list-video-jobs", "fetch-video"]:
        assert c in r.output


def test_help_lists_magnific_command():
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    assert "generate-magnific" in r.output


def test_help_lists_fal_commands():
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    assert "fal-run" in r.output
    assert "fal-list-workflows" in r.output


def test_fal_run_invalid_json_returns_structured_error(tmp_path):
    r = runner.invoke(app, ["fal-run", str(tmp_path), "fal-ai/nano-banana-pro", "{nope"])
    assert r.exit_code == 1
    assert '"backend": "fal"' in r.output
    assert "INPUT_JSON must be a JSON object" in r.output


def test_fal_run_json_array_returns_structured_error(tmp_path):
    r = runner.invoke(app, ["fal-run", str(tmp_path), "fal-ai/nano-banana-pro", "[]"])
    assert r.exit_code == 1
    assert '"status": "error"' in r.output
    assert "JSON object" in r.output


def test_help_lists_replicate_command():
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    assert "replicate-run" in r.output


@pytest.mark.parametrize("payload", ["{nope", "[]"])
def test_replicate_run_bad_json_returns_structured_error(tmp_path, payload):
    r = runner.invoke(app, ["replicate-run", str(tmp_path), "owner/model", payload])
    assert r.exit_code == 1
    assert '"backend": "replicate"' in r.output
    assert "INPUT_JSON must be a JSON object" in r.output
