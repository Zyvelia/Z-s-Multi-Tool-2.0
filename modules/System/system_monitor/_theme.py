"""
Fallback theme — used only when System Monitor runs standalone (outside
the full app). Chart stat colors match modules/System/system_monitor/colors.py.
"""

import hashlib
import customtkinter as ctk
from core import theme


OK = "#3ddc84"
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