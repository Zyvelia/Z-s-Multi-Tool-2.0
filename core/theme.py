# core/theme.py
"""
Shared visual theme for Z's Multi Tool.

Every page AND every module pulls its colors/fonts/spacing from here.
Modules used to each hardcode their own copy of the same palette
(BG/PANEL/ACCENT/...); centralizing it means the whole app is
guaranteed to look like one product, and re-skinning it later is a
one-file change instead of a fifteen-file hunt.
"""

import customtkinter as ctk
import hashlib

# =====================================================
# COLORS
# =====================================================

BG = "#0f1115"           # window / page background
PANEL = "#151922"        # cards, panels, section containers
PANEL_2 = "#1b2030"      # secondary buttons, inputs, "CARD"/"raised" surfaces
PANEL_HOVER = "#212739"  # hover state for cards/panels
BORDER = "#252d3d"       # subtle separators / card borders

ACCENT = "#a78bfa"
ACCENT_HOVER = "#c4b5fd"
ACCENT_DIM = "#8b5cf6"
ACCENT_MUTED = "#3b2f63"

DANGER = "#b33939"
DANGER_BG = "#2a1b1b"
DANGER_HOVER = "#d14b4b"

SUCCESS = "#2ecc71"
ERROR = "#ff5c5c"

TEXT = "#e6e6e6"
MUTED = "#9aa4b2"
FAINT = "#5c6474"

# Aliases matching the various names modules already used, so modules
# can `from core import theme as t` and reference whichever name reads
# best, without every module needing the exact same variable name.
CARD = PANEL_2
BG_PANEL = PANEL
BG_RAISED = PANEL_2
TEXT_HI = TEXT
TEXT_MID = MUTED
TEXT_LOW = FAINT
RED = DANGER
RED_DIM = "#8f2d2d"
ACCENT_GLOW = "#211a35"   # faint tinted fill, used behind selected rows/tabs

# =====================================================
# FONTS
# =====================================================

FONT_FAMILY = "Segoe UI"
MONO_FAMILY = "Consolas"


def font(size: int, weight: str = "normal") -> ctk.CTkFont:
    """Themed proportional font (falls back to the system default on
    platforms without Segoe UI installed)."""
    return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)


def mono(size: int, weight: str = "normal") -> ctk.CTkFont:
    """Themed monospace font, for logs / hashes / stats readouts."""
    return ctk.CTkFont(family=MONO_FAMILY, size=size, weight=weight)


# =====================================================
# SPACING / SHAPE
# =====================================================

PAD = 10
PAD_LG = 20
RADIUS = 14
RADIUS_SM = 8


# =====================================================
# WIDGET STYLE PRESETS
# =====================================================

def primary_button_style() -> dict:
    return dict(
        fg_color=ACCENT,
        hover_color=ACCENT_HOVER,
        text_color="#0b0d10",
        corner_radius=RADIUS_SM,
        font=font(13, "bold"),
    )


def secondary_button_style() -> dict:
    return dict(
        fg_color=PANEL_2,
        hover_color=PANEL_HOVER,
        text_color=TEXT,
        corner_radius=RADIUS_SM,
        font=font(13),
    )


def danger_button_style() -> dict:
    return dict(
        fg_color=DANGER_BG,
        hover_color=DANGER_HOVER,
        text_color=DANGER,
        corner_radius=RADIUS_SM,
        font=font(13, "bold"),
    )


def panel_style() -> dict:
    return dict(
        fg_color=PANEL,
        corner_radius=RADIUS,
    )


def apply_appearance():
    """Call once, before any widgets are created (in App.__init__)."""
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")


# =====================================================
# STABLE ACCENT COLORS
# =====================================================
# A small set of hues that all read fine against PANEL. Uses hashlib
# rather than Python's built-in hash() — hash() is randomized per process
# (PYTHONHASHSEED) by default, so the same string maps to a different
# color every launch; hashlib gives the same color every time.

ACCENT_HUES = ["#4ea1ff", "#a78bfa", "#34d399", "#fb923c", "#f472b6", "#38bdf8", "#facc15"]


def hash_color(key: str) -> str:
    """Deterministic accent color for a given string (e.g. a tool or item
    name) — same input always maps to the same color, across runs."""
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()
    return ACCENT_HUES[int(digest[:8], 16) % len(ACCENT_HUES)]
