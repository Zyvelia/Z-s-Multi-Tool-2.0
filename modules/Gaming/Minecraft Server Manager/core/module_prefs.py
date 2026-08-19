"""Module-wide preferences (terminal color scheme, etc.)."""

from __future__ import annotations

import json
from pathlib import Path

try:
    from core import paths  # type: ignore

    def _prefs_file() -> Path:
        return Path(paths.data_path("game_servers", "module_prefs.json"))
except ImportError:  # pragma: no cover
    import os

    def _prefs_file() -> Path:
        base = Path(os.environ.get("APPDATA", Path.home())) / "ZsMultiTool" / "game_servers"
        base.mkdir(parents=True, exist_ok=True)
        return base / "module_prefs.json"


DEFAULT_PREFS = {
    "terminal_scheme": "default",
    "palworld_save_hint_dismissed": False,
    "quick_commands_expanded": False,
}

TERMINAL_SCHEMES: dict[str, dict[str, str]] = {
    "default": {
        "manager": "#7fa8d9",
        "command": "#d4a8ff",
        "log_error": "#ff6b6b",
        "log_warn": "#f0c040",
        "log_info": "#7ec8e8",
        "log_debug": "#6b7a8f",
        "log_join": "#6fd97a",
        "log_leave": "#f09868",
        "log_ready": "#98e6a0",
        "log_save": "#c4a8f0",
        "log_admin": "#f0a0c8",
        "log_chat": "#e8eaed",
        "log_rcon": "#a8c8ff",
        "log_install": "#88d9c8",
        "log_default": "#b0b8c8",
    },
    "dracula": {
        "manager": "#8be9fd",
        "command": "#bd93f9",
        "log_error": "#ff5555",
        "log_warn": "#ffb86c",
        "log_info": "#8be9fd",
        "log_debug": "#6272a4",
        "log_join": "#50fa7b",
        "log_leave": "#ffb86c",
        "log_ready": "#50fa7b",
        "log_save": "#bd93f9",
        "log_admin": "#ff79c6",
        "log_chat": "#f8f8f2",
        "log_rcon": "#8be9fd",
        "log_install": "#50fa7b",
        "log_default": "#bbbbbb",
    },
    "monokai": {
        "manager": "#66d9ef",
        "command": "#ae81ff",
        "log_error": "#f92672",
        "log_warn": "#e6db74",
        "log_info": "#66d9ef",
        "log_debug": "#75715e",
        "log_join": "#a6e22e",
        "log_leave": "#fd971f",
        "log_ready": "#a6e22e",
        "log_save": "#ae81ff",
        "log_admin": "#f92672",
        "log_chat": "#f8f8f2",
        "log_rcon": "#66d9ef",
        "log_install": "#a6e22e",
        "log_default": "#cfcfc2",
    },
    "solarized": {
        "manager": "#268bd2",
        "command": "#6c71c4",
        "log_error": "#dc322f",
        "log_warn": "#b58900",
        "log_info": "#2aa198",
        "log_debug": "#586e75",
        "log_join": "#859900",
        "log_leave": "#cb4b16",
        "log_ready": "#859900",
        "log_save": "#6c71c4",
        "log_admin": "#d33682",
        "log_chat": "#fdf6e3",
        "log_rcon": "#268bd2",
        "log_install": "#859900",
        "log_default": "#93a1a1",
    },
    "high_contrast": {
        "manager": "#00ffff",
        "command": "#ff00ff",
        "log_error": "#ff4444",
        "log_warn": "#ffff00",
        "log_info": "#00ccff",
        "log_debug": "#888888",
        "log_join": "#00ff00",
        "log_leave": "#ff8800",
        "log_ready": "#00ff88",
        "log_save": "#cc88ff",
        "log_admin": "#ff66cc",
        "log_chat": "#ffffff",
        "log_rcon": "#88ccff",
        "log_install": "#00ff88",
        "log_default": "#dddddd",
    },
}


def load_prefs() -> dict:
    f = _prefs_file()
    if f.exists():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merged = dict(DEFAULT_PREFS)
                merged.update(data)
                return merged
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULT_PREFS)


def save_prefs(prefs: dict) -> None:
    try:
        _prefs_file().write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    except OSError:
        pass


def scheme_colors(scheme: str) -> dict[str, str]:
    return dict(TERMINAL_SCHEMES.get(scheme, TERMINAL_SCHEMES["default"]))
