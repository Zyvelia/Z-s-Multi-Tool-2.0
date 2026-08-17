"""
tree_preview.py
---------------
Renders a simple Explorer-style ASCII tree for one game record under a
chosen output folder, so the user can see exactly what "Create" will do:

    D:\\Launchers
    └── Neverness To Everness
        └── Client
            └── WindowsNoEditor
                └── HT
                    └── Binaries
                        └── Win64
                            └── HTGame.exe

Since a game record only ever describes one executable, the resulting tree
is always a single unbranching chain of folders ending in a file - there's
no need for a generic multi-branch tree renderer here.
"""

from __future__ import annotations

from typing import List, Optional

from .game_database import GameRecord


def render_tree(game: Optional[GameRecord], output_root: str = "") -> str:
    """Render the folder chain that will be created for `game` under `output_root`."""
    if game is None:
        return "Select a game to preview its folder structure."

    root_label = output_root.strip() or "(choose an output folder)"
    parts = game.exe_parts

    if not parts:
        return f"{root_label}\n└── (no executable path defined for this game)"

    lines = [root_label]
    _render_chain(parts, "", lines)
    return "\n".join(lines)


def _render_chain(parts: List[str], prefix: str, lines: List[str]) -> None:
    """Render a single unbranching chain - every segment has exactly one child."""
    if not parts:
        return
    head, rest = parts[0], parts[1:]
    lines.append(f"{prefix}└── {head}")
    _render_chain(rest, prefix + "    ", lines)
