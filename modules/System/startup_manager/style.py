# modules/System/startup_manager/style.py
"""Startup Manager's own accent — amber, distinct from System Monitor's
blue so the two System-category tools don't blur together."""

from core.theme import make_module_theme

theme = make_module_theme(
    ACCENT="#fb923c",
    ACCENT_HOVER="#fdba74",
    ACCENT_DIM="#ea7c1e",
)
