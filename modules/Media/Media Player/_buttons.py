"""Music / video player button styles — secondary controls use a cool tone
so they stay readable on warm neon themes (magenta accent)."""

from __future__ import annotations

import customtkinter as ctk

from core import theme


def _accent_is_warm() -> bool:
    """True when the module accent reads red/magenta (neon presets)."""
    raw = theme.ACCENT.lstrip("#")
    if len(raw) != 6:
        return False
    r = int(raw[0:2], 16)
    g = int(raw[2:4], 16)
    b = int(raw[4:6], 16)
    return r > max(g, b) + 40


def cool_button_kwargs(**overrides) -> dict:
    """Secondary / utility buttons — cyan-slate on warm themes, theme secondary otherwise."""
    if _accent_is_warm():
        kw = dict(
            fg_color="#142530",
            hover_color="#1c3344",
            text_color="#64c8ff",
            border_width=1,
            border_color="#286080",
            corner_radius=theme.RADIUS_SM,
            font=theme.font(13),
            height=34,
        )
    else:
        kw = theme.secondary_button_kwargs()
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", theme.BORDER)
    kw.update(overrides)
    return kw


def make_btn(parent, text, cmd, **overrides):
    return ctk.CTkButton(parent, text=text, command=cmd, **cool_button_kwargs(**overrides))


def apply_cool_button(widget, **overrides) -> None:
    widget.configure(**cool_button_kwargs(**overrides))


def icon_btn_kwargs(**overrides) -> dict:
    return cool_button_kwargs(
        width=46, height=44, corner_radius=10, font=("Segoe UI", 15), **overrides
    )


def cool_accent() -> str:
    """Accent for sliders/progress when warm themes need contrast."""
    return "#64c8ff" if _accent_is_warm() else theme.ACCENT


def cool_accent_hover() -> str:
    return "#8ad8ff" if _accent_is_warm() else theme.ACCENT_HOVER


def highlight_fill() -> str:
    """Filled highlight for Shuffle All and the active track row."""
    return "#1a6a9a" if _accent_is_warm() else theme.ACCENT


def highlight_fill_hover() -> str:
    return "#2280b8" if _accent_is_warm() else theme.ACCENT_HOVER


def highlight_text() -> str:
    return "#ffffff" if _accent_is_warm() else "#0b0d10"


def highlight_border() -> str:
    return "#64c8ff" if _accent_is_warm() else theme.ACCENT


def highlight_action_kwargs(**overrides) -> dict:
    """Prominent player actions — cyan on warm themes, accent elsewhere."""
    kw = dict(
        fg_color=highlight_fill(),
        hover_color=highlight_fill_hover(),
        text_color=highlight_text(),
        border_width=1,
        border_color=highlight_border(),
        corner_radius=theme.RADIUS_SM,
        font=theme.font(13, "bold"),
        height=34,
    )
    kw.update(overrides)
    return kw


def play_button_kwargs(**overrides) -> dict:
    """Main transport play button."""
    kw = highlight_action_kwargs(
        width=64, height=44, corner_radius=10, font=("Segoe UI", 15),
    )
    kw.update(overrides)
    return kw


def seek_bar_kwargs(*, t=None, **overrides) -> dict:
    """Seek slider — same accent palette as the Now Playing card."""
    pal = t or theme
    kw = dict(
        fg_color=pal.ACCENT_MUTED,
        progress_color=pal.ACCENT,
        button_color=pal.ACCENT_HOVER,
        button_hover_color=pal.ACCENT_HOVER,
        border_width=0,
        corner_radius=10,
    )
    kw.update(overrides)
    return kw


def selected_track_kwargs(**overrides) -> dict:
    """Active playlist row styling."""
    fill = highlight_fill()
    kw = dict(
        fg_color=fill,
        hover_color=fill,
        text_color=highlight_text(),
        font=("Segoe UI", 13, "bold"),
        border_color=highlight_border(),
    )
    kw.update(overrides)
    return kw
