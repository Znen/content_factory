"""Shared core builder — reused by CLI and MCP server (avoids kf's _core/build_server dup)."""

from dataclasses import dataclass
from .config import Settings, load_settings


@dataclass
class Core:
    settings: Settings


def build_core(settings: "Settings | None" = None) -> Core:
    return Core(settings=settings or load_settings())
