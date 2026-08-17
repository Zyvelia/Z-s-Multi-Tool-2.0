"""
Fallback theme — used only when this module is NOT running inside
Zs Multi Tool (i.e. there's no `core.theme` to import, so style.py's
`from core.theme import make_module_theme` fails too). Keeps the exact
same tokens *and* the same per-metric/per-core color scheme as
style.py, so the look is identical either way.
"""

import hashlib
import customtkinter as ctk


BG = "#0f1115"
PANEL = "#151922"
PANEL_2 = "#1b2030"
ACCENT = "#4ea1ff"
DANGER = "#ff5c5c"
OK = "#3ddc84"
MUTED = "#7d8494"
FAINT = "#565d6e"
TEXT = "#e8edf5"

ACCENT_HUES = [
    "#4ea1ff", "#a78bfa", "#34d399", "#fb923c",
    "#f472b6", "#38bdf8", "#facc15", "#60a5fa",
]

METRIC_COLORS = {
    "cpu": "#4ea1ff",
    "ram": "#a78bfa",
    "disk": "#fb923c",
    "swap": "#34d399",
}


def font(size, weight="normal"):
    return ctk.CTkFont(size=size, weight=weight)


def mono(size):
    return ctk.CTkFont(family="Consolas", size=size)


def core_color(index: int) -> str:
    digest = hashlib.md5(str(index).encode("utf-8")).hexdigest()
    return ACCENT_HUES[int(digest[:8], 16) % len(ACCENT_HUES)]
