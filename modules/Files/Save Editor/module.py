"""
module.py — Module descriptor for Save Editor.
Holds module-level metadata and configuration constants.
"""

from __future__ import annotations

MODULE_NAME     = "Save Editor"
MODULE_VERSION  = "1.1.0"
MODULE_AUTHOR   = "Vault System"
MODULE_DESC     = (
    "Open, inspect, and edit game save files — JSON, XML, YAML, INI, "
    "gzip/zlib/base64-wrapped saves, encrypted saves (AES/XOR via saved "
    "per-game profiles), and unrecognized binary saves. Custom layouts give "
    "any of these a named-field form (Gold, Coins, Player Name, ...); "
    "binary saves without a layout still get a Readable Text view and a "
    "numeric value search on top of raw hex, so a field can be found and "
    "named for any game, not just the ones with a built-in profile."
)
MODULE_ICON     = "💾"
MODULE_CATEGORY = "Files"

# Structured formats get the tree editor; anything undetected falls back
# to the raw hex view.
STRUCTURED_FORMATS = {"json", "xml", "yaml", "ini"}
WRAPPER_FORMATS     = {"gzip", "zlib", "base64"}

# Hex view: how many bytes per line, and a soft cap before we warn about
# editing very large raw files in a plain text widget.
HEX_BYTES_PER_LINE = 16
HEX_SIZE_WARN_BYTES = 2 * 1024 * 1024  # 2 MB

# Per-game decryption profiles (algo + key) live in one JSON file under
# this module's slice of AppData, via core.paths if it's importable.
PROFILES_FILENAME = "save_editor_profiles.json"
LAYOUTS_FILENAME = "save_editor_layouts.json"
VIEW_PROFILES_FILENAME = "save_editor_view_profiles.json"


def profiles_path() -> str:
    return _data_file(PROFILES_FILENAME)


def layouts_path() -> str:
    return _data_file(LAYOUTS_FILENAME)


def view_profiles_path() -> str:
    return _data_file(VIEW_PROFILES_FILENAME)


def _data_file(filename: str) -> str:
    try:
        from core.paths import get_data_dir  # matches the rest of Zs Multi Tool
        return str(get_data_dir("Save Editor") / filename)
    except Exception:
        # standalone fallback: next to this file
        import os
        return os.path.join(os.path.dirname(__file__), filename)
