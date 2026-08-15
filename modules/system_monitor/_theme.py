"""
Fallback theme — used only when this module is NOT running inside
Zs Multi Tool (i.e. there's no `core.theme` to import). Keeps the exact
same tokens as core/theme.py so the look is identical either way.
"""

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


def font(size, weight="normal"):
    return ctk.CTkFont(size=size, weight=weight)


def mono(size):
    return ctk.CTkFont(family="Consolas", size=size)
