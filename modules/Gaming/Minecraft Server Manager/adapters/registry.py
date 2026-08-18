"""Adapter registry — lookup game types by id."""

from __future__ import annotations

from .base import GameServerAdapter
from .games import (
    CustomServerAdapter,
    PalworldAdapter,
    ProjectZomboidAdapter,
    SatisfactoryAdapter,
    SteamCmdAdapter,
    TerrariaAdapter,
    ValheimAdapter,
)
from .minecraft_bedrock import MinecraftBedrockAdapter
from .minecraft_java import MinecraftJavaAdapter

_ADAPTERS: dict[str, GameServerAdapter] = {}


def _register(adapter: GameServerAdapter) -> None:
    _ADAPTERS[adapter.game_type] = adapter


def register_all() -> None:
    if _ADAPTERS:
        return
    for adapter in (
        MinecraftJavaAdapter(),
        MinecraftBedrockAdapter(),
        SatisfactoryAdapter(),
        TerrariaAdapter(),
        ValheimAdapter(),
        PalworldAdapter(),
        ProjectZomboidAdapter(),
        SteamCmdAdapter(),
        CustomServerAdapter(),
    ):
        _register(adapter)


def get_adapter(game_type: str) -> GameServerAdapter | None:
    register_all()
    return _ADAPTERS.get(game_type)


def all_adapters() -> list[GameServerAdapter]:
    register_all()
    return list(_ADAPTERS.values())


def game_choices() -> list[tuple[str, str, str]]:
    """Return (game_type, display_name, icon) for wizard menus."""
    return [(a.game_type, a.display_name, a.icon) for a in all_adapters()]
