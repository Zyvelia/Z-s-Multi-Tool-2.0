# modules/system_monitor/style.py
"""
System Monitor's own accent set — the first module in the app to move
to a per-module style.py (see core/theme.py's module docstring for the
override pattern this follows).

Problem this fixes: every bar in this page (the 4 metric cards *and*
every per-core bar) rendered in the same shared ACCENT blue, only
switching color when a metric crossed the danger threshold. At a
glance you couldn't tell CPU from RAM from Disk without reading the
percentage text. Each metric now gets its own base color; per-core
bars cycle through a wider hue set so an 8/16/32-core grid doesn't
read as one solid block. Danger-red on high usage still overrides
everything below, unchanged.
"""

from core.theme import make_module_theme

theme = make_module_theme(
    ACCENT="#4ea1ff",                 # CPU keeps the app's default blue
    ACCENT_HUES=[                      # per-core bar palette (see core_color)
        "#4ea1ff", "#a78bfa", "#34d399", "#fb923c",
        "#f472b6", "#38bdf8", "#facc15", "#60a5fa",
    ],
)

# One base color per metric card. This isn't a core theme token (core/theme.py
# has no concept of "one accent per metric"), so it lives here instead of as
# a Theme override.
METRIC_COLORS = {
    "cpu": "#4ea1ff",    # blue
    "ram": "#a78bfa",    # purple
    "disk": "#fb923c",   # orange
    "swap": "#34d399",   # green/teal
}


def core_color(index: int) -> str:
    """Stable, distinct color per CPU core index — same core always gets
    the same color across refreshes (and app restarts), it's just not the
    same color as every other core."""
    return theme.hash_color(str(index))
