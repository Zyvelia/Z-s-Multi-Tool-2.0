# core/theme.py
"""
Shared visual theme for Z's Multi Tool.

Every page AND every module pulls its colors/fonts/spacing from here.
Modules used to each hardcode their own copy of the same palette
(BG/PANEL/ACCENT/...); centralizing it means the whole app is
guaranteed to look like one product, and re-skinning it later is a
one-file change instead of a fifteen-file hunt.

Per-module overrides
---------------------
Most modules should just use the module-level constants/functions
below (`t.ACCENT`, `t.primary_button_style()`, ...) exactly like
before — nothing about that changed.

A module that wants its *own* accent color (e.g. Gaming Hub going
green instead of purple) doesn't need to fork the whole palette.
Drop a `style.py` in that module's own folder:

    # modules/gaming_hub/style.py
    from core.theme import make_module_theme

    theme = make_module_theme(
        ACCENT="#34d399",
        ACCENT_HOVER="#6ee7b7",
        ACCENT_DIM="#10b981",
    )

then import it locally instead of the shared theme:

    from .style import theme as t
    ...
    ctk.CTkButton(parent, text="Backup", **t.primary_button_style())

`t` behaves exactly like `core.theme` (same attributes, same
`font()`/`primary_button_style()`/etc. methods) except the colors
you overrode are swapped in everywhere those helpers use them.
Everything you *don't* override (spacing, radius, fonts, BG/PANEL/
TEXT/...) is inherited from the shared theme, so the module still
looks like part of the same app.
"""

import customtkinter as ctk
import hashlib

# =====================================================
# COLORS (shared defaults)
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

# =====================================================
# SPACING / SHAPE
# =====================================================

PAD = 10
PAD_LG = 20
RADIUS = 14
RADIUS_SM = 8

# =====================================================
# STABLE ACCENT COLORS
# =====================================================
# A small set of hues that all read fine against PANEL. Uses hashlib
# rather than Python's built-in hash() — hash() is randomized per process
# (PYTHONHASHSEED) by default, so the same string maps to a different
# color every launch; hashlib gives the same color every time.

ACCENT_HUES = ["#4ea1ff", "#a78bfa", "#34d399", "#fb923c", "#f472b6", "#38bdf8", "#facc15"]

# Every constant above that a module might reasonably want to override.
# Used by Theme.__init__ to seed an instance's defaults and to validate
# override kwargs (typo'ing an override name fails loudly instead of
# silently creating an unused attribute).
_TOKEN_NAMES = [
    "BG", "PANEL", "PANEL_2", "PANEL_HOVER", "BORDER",
    "ACCENT", "ACCENT_HOVER", "ACCENT_DIM", "ACCENT_MUTED",
    "DANGER", "DANGER_BG", "DANGER_HOVER",
    "SUCCESS", "ERROR",
    "TEXT", "MUTED", "FAINT",
    "CARD", "BG_PANEL", "BG_RAISED", "TEXT_HI", "TEXT_MID", "TEXT_LOW",
    "RED", "RED_DIM", "ACCENT_GLOW",
    "FONT_FAMILY", "MONO_FAMILY",
    "PAD", "PAD_LG", "RADIUS", "RADIUS_SM",
    "ACCENT_HUES",
]


class Theme:
    """A bundle of colors/fonts/spacing plus the style-preset helpers.

    The module-level constants and functions below (`theme.ACCENT`,
    `theme.font()`, `theme.primary_button_style()`, ...) are just the
    default `Theme()` instance exposed at module scope, so every
    existing `from core import theme as t` call site keeps working
    unchanged. `make_module_theme()` creates additional instances with
    a subset of tokens overridden — see the module docstring above.
    """

    def __init__(self, **overrides):
        module_globals = globals()
        for name in _TOKEN_NAMES:
            setattr(self, name, module_globals[name])

        unknown = set(overrides) - set(_TOKEN_NAMES)
        if unknown:
            raise ValueError(
                f"Unknown theme token(s) {sorted(unknown)} — check spelling "
                f"against the constants defined in core/theme.py."
            )
        for name, value in overrides.items():
            setattr(self, name, value)

    # ---- fonts ----

    def font(self, size: int, weight: str = "normal") -> ctk.CTkFont:
        """Themed proportional font (falls back to the system default on
        platforms without Segoe UI installed)."""
        return ctk.CTkFont(family=self.FONT_FAMILY, size=size, weight=weight)

    def mono(self, size: int, weight: str = "normal") -> ctk.CTkFont:
        """Themed monospace font, for logs / hashes / stats readouts."""
        return ctk.CTkFont(family=self.MONO_FAMILY, size=size, weight=weight)

    # ---- widget style presets ----

    def primary_button_style(self) -> dict:
        return dict(
            fg_color=self.ACCENT,
            hover_color=self.ACCENT_HOVER,
            text_color="#0b0d10",
            corner_radius=self.RADIUS_SM,
            font=self.font(13, "bold"),
        )

    def secondary_button_style(self) -> dict:
        return dict(
            fg_color=self.PANEL_2,
            hover_color=self.PANEL_HOVER,
            text_color=self.TEXT,
            corner_radius=self.RADIUS_SM,
            font=self.font(13),
        )

    def danger_button_style(self) -> dict:
        return dict(
            fg_color=self.DANGER_BG,
            hover_color=self.DANGER_HOVER,
            text_color=self.DANGER,
            corner_radius=self.RADIUS_SM,
            font=self.font(13, "bold"),
        )

    def panel_style(self) -> dict:
        return dict(
            fg_color=self.PANEL,
            corner_radius=self.RADIUS,
        )

    # ---- misc ----

    def apply_appearance(self):
        """Call once, before any widgets are created (in App.__init__)."""
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

    def hash_color(self, key: str) -> str:
        """Deterministic accent color for a given string (e.g. a tool or
        item name) — same input always maps to the same color, across
        runs. Picks from this theme's own ACCENT_HUES, so a module that
        overrides ACCENT_HUES gets matching per-item colors too."""
        digest = hashlib.md5(key.encode("utf-8")).hexdigest()
        return self.ACCENT_HUES[int(digest[:8], 16) % len(self.ACCENT_HUES)]


# =====================================================
# DEFAULT (SHARED) THEME — module-level API, unchanged for callers
# =====================================================

_default = Theme()


def font(size: int, weight: str = "normal") -> ctk.CTkFont:
    return _default.font(size, weight)


def mono(size: int, weight: str = "normal") -> ctk.CTkFont:
    return _default.mono(size, weight)


def primary_button_style() -> dict:
    return _default.primary_button_style()


def secondary_button_style() -> dict:
    return _default.secondary_button_style()


def danger_button_style() -> dict:
    return _default.danger_button_style()


def panel_style() -> dict:
    return _default.panel_style()


def apply_appearance():
    _default.apply_appearance()


def hash_color(key: str) -> str:
    return _default.hash_color(key)


def make_module_theme(**overrides) -> Theme:
    """Create a Theme for one module's own style.py, inheriting every
    shared token (spacing, fonts, BG/PANEL/TEXT/...) and overriding
    only the ones passed in, e.g.:

        theme = make_module_theme(ACCENT="#34d399", ACCENT_HOVER="#6ee7b7")

    Raises ValueError on an unrecognized token name (likely a typo).
    """
    return Theme(**overrides)