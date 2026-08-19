"""Layout presets for Game Server Manager (uses shared core.theme tokens)."""

from core import theme as t


def card_style(*, fg: str | None = None) -> dict:
    return dict(
        fg_color=fg or t.PANEL_2,
        corner_radius=t.RADIUS_SM,
        border_width=1,
        border_color=t.BORDER,
    )


def surface_style() -> dict:
    return dict(
        fg_color=t.PANEL,
        corner_radius=t.RADIUS,
        border_width=1,
        border_color=t.BORDER,
    )


def inset_style() -> dict:
    return dict(
        fg_color=t.PANEL_HOVER,
        corner_radius=t.RADIUS_SM,
        border_width=1,
        border_color=t.BORDER,
    )


def accent_strip(width: int = 4) -> dict:
    return dict(
        fg_color=t.ACCENT,
        corner_radius=2,
        width=width,
    )


def status_pill_style(running: bool, restarting: bool = False) -> dict:
    if restarting:
        return dict(fg_color=t.ACCENT_GLOW, text_color=t.ACCENT, corner_radius=20)
    if running:
        return dict(fg_color=t.ACCENT_MUTED, text_color=t.SUCCESS, corner_radius=20)
    return dict(fg_color=t.PANEL_HOVER, text_color=t.MUTED, corner_radius=20)
