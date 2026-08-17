# modules/System/driver_checker/style.py
"""Driver/Update Checker's own accent — sky blue, distinct from System
Monitor's default blue, Startup Manager's amber, and Duplicate File
Finder's teal."""

from core.theme import make_module_theme

theme = make_module_theme(
    ACCENT="#38bdf8",
    ACCENT_HOVER="#7dd3fc",
    ACCENT_DIM="#0ea5e9",
)
