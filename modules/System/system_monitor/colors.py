"""Stat/chart colors for System Monitor.

UI chrome follows the active module theme (neon, violet, classic, …).
Metric bars use a fixed high-contrast palette so CPU / RAM / Disk / Swap
stay easy to tell apart on pure-black and neon-magenta backgrounds — the
theme ACCENT_HUES are often all in one hue family and would look identical.
"""

from core import theme

# Distinct functional colors — tuned for dark panels, independent of accent.
CHART_METRIC_COLORS: dict[str, str] = {
    "cpu": "#4ea1ff",   # blue
    "ram": "#a78bfa",   # purple
    "disk": "#fb923c",  # orange
    "swap": "#34d399",  # teal
}

# Per-core bars cycle through a wide hue set (not theme accent hashes).
CORE_BAR_HUES: list[str] = [
    "#4ea1ff",
    "#a78bfa",
    "#34d399",
    "#fb923c",
    "#f472b6",
    "#38bdf8",
    "#facc15",
    "#60a5fa",
]


def metric_color(key: str) -> str:
    return CHART_METRIC_COLORS.get(key, theme.ACCENT)


def metric_colors() -> dict[str, str]:
    return dict(CHART_METRIC_COLORS)


def core_color(index: int) -> str:
    return CORE_BAR_HUES[index % len(CORE_BAR_HUES)]
