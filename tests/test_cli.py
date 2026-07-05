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
