# modules/Gaming/Minecraft Server Manager/style.py
"""Game Server Manager theme — grass green accent + layout helpers."""

from core.theme import make_module_theme

theme = make_module_theme(
    ACCENT="#5fb85a",
    ACCENT_HOVER="#7fd07a",
    ACCENT_DIM="#4a9645",
)

# Status colors for server list / overview cards
STATUS_RUNNING = "#5fb85a"
STATUS_STARTING = "#e8b339"
STATUS_STOPPED = theme.MUTED


def card_style(fg=None) -> dict:
    return {
        "fg_color": fg or theme.PANEL_2,
        "corner_radius": theme.RADIUS_SM,
        "border_width": 1,
        "border_color": theme.BORDER,
    }


def selected_card_style() -> dict:
    return {
        "fg_color": theme.ACCENT_DIM,
        "corner_radius": theme.RADIUS_SM,
        "border_width": 1,
        "border_color": theme.ACCENT,
    }


def stat_pill_style() -> dict:
    return {
        "fg_color": theme.PANEL_2,
        "corner_radius": theme.RADIUS_SM,
        "height": 28,
    }


def section_header_style() -> dict:
    return {"font": theme.font(13, "bold"), "text_color": theme.TEXT}


def hint_style() -> dict:
    return {"font": theme.font(11), "text_color": theme.MUTED}
