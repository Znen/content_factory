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


def main():
    import sys
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    app()
