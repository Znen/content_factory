"""Content Factory CLI — serve the MCP gateway or run one-off generations for smoke tests."""

import json
from typing import List, Optional

import typer

from . import __version__

app = typer.Typer(help="Content Factory (generation-factory) CLI", no_args_is_help=True)


@app.command()
def version():
    """Print version."""
    typer.echo(f"content-factory {__version__}")


@app.command()
def serve(http: bool = typer.Option(False, help="HTTP transport instead of stdio")):
    """Run the generation-factory MCP gateway."""
    from .mcp_server import run_server
    run_server(http=http)


@app.command("generate-draft")
def generate_draft(project: str, prompt: str,
                   n: int = typer.Option(4, help="number of drafts"),
                   negative: str = typer.Option("", help="negative prompt"),
                   seed: int = typer.Option(0, help="seed")):
    """ComfyUI drafts (manual smoke; requires ComfyUI on GF_COMFYUI_URL)."""
    from .core import build_core
    from .mcp_server import _generate_draft_impl
    out = _generate_draft_impl(project, prompt, n, negative, seed, settings=build_core().settings)
    typer.echo(json.dumps(out, ensure_ascii=False, indent=2))


@app.command("generate-final")
def generate_final(project: str, prompt: str,
                   ref: Optional[List[str]] = typer.Option(None, help="reference image (repeatable)"),
                   aspect: str = typer.Option("9:16", help="aspect ratio")):
    """Nano Banana final (manual smoke; requires Nitro server on GF_NANO_SERVER_URL)."""
    from .core import build_core
    from .mcp_server import _generate_final_impl
    out = _generate_final_impl(project, prompt, ref or [], aspect, settings=build_core().settings)
    typer.echo(json.dumps(out, ensure_ascii=False, indent=2))


def _echo(result: dict) -> None:
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("add-variant")
def add_variant_cmd(project: str, image_path: str, set_id: str,
                    note: str = typer.Option("", help="комментарий-провенанс"),
                    date: str = typer.Option("", help="YYYY-MM-DD (lineart/final)"),
                    stage: str = typer.Option("", help="стем итерации, напр. magnific")):
    """Скопировать вариант в набор под каноничным именем (источник не трогается)."""
    from .curate import add_variant
    _echo(add_variant(project, image_path, set_id, note=note,
                      date=date or None, stage=stage or None))


@app.command("set-winner")
def set_winner_cmd(project: str, set_id: str, image_path: str):
    """Переставить winner-указатель набора (пиксели не двигаются)."""
    from .curate import set_winner
    _echo(set_winner(project, set_id, image_path))


@app.command("list-sets")
def list_sets_cmd(project: str, kind: str = typer.Option("", help="фильтр по kind")):
    """Инвентарь наборов: варианты, winner'ы."""
    from .curate import list_sets
    _echo(list_sets(project, kind=kind or None))


@app.command("materialize-winners")
def materialize_winners_cmd(project: str):
    """Пересобрать папку winners/ из манифеста и истории."""
    from .curate import materialize_winners
    _echo(materialize_winners(project))


@app.command("discard")
def discard_cmd(project: str, image_path: str):
    """Мягкое удаление в _TO_PURGE (hard-delete не существует)."""
    from .curate import discard
    _echo(discard(project, image_path))


@app.command("adopt-set")
def adopt_set_cmd(project: str, set_id: str, dir: str):
    """Зарегистрировать существующую папку как историю набора (без перемещений)."""
    from .curate import adopt_set
    _echo(adopt_set(project, set_id, dir))


def main():
    import sys
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    app()


if __name__ == "__main__":  # enables `python -m gf.cli` (Hermes stdio launch)
    main()
