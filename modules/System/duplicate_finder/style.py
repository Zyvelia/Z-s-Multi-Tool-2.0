# modules/System/duplicate_finder/style.py
"""Duplicate File Finder's own accent — teal, distinct from System
Monitor's blue and Startup Manager's amber."""

from core.theme import make_module_theme

theme = make_module_theme(
    ACCENT="#2dd4bf",
    ACCENT_HOVER="#5eead4",
    ACCENT_DIM="#14b8a6",
)
