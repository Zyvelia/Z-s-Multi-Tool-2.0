"""Catalog (home) page themes — selectable from Settings."""

from dataclasses import dataclass

from core import theme as core_theme
from core.theme import make_module_theme, Theme

DEFAULT_CATALOG_THEME = "neon"


@dataclass(frozen=True)
class CatalogThemeBundle:
    id: str
    name: str
    description: str
    t: Theme
    on_accent: str
    scroll_track: str
    scroll_thumb: str
    scroll_thumb_hover: str


def _bundle(
    id: str,
    name: str,
    description: str,
    on_accent: str,
    scroll_track: str,
    scroll_thumb: str,
    scroll_thumb_hover: str,
    **colors,
) -> CatalogThemeBundle:
    return CatalogThemeBundle(
        id=id,
        name=name,
        description=description,
        t=make_module_theme(**colors),
        on_accent=on_accent,
        scroll_track=scroll_track,
        scroll_thumb=scroll_thumb,
        scroll_thumb_hover=scroll_thumb_hover,
    )


# ── Presets ─────────────────────────────────────────────────────────────

_PRESETS: dict[str, CatalogThemeBundle] = {}

_PRESETS["neon"] = _bundle(
    id="neon",
    name="Neon Pulse",
    description="Bright cyberpunk magenta — high energy.",
    on_accent="#0a0006",
    scroll_track="#000000",
    scroll_thumb="#8B0050",
    scroll_thumb_hover="#E6007E",
    BG="#000000",
    PANEL="#0a0008",
    PANEL_2="#14000e",
    PANEL_HOVER="#240016",
    BORDER="#6b2458",
    ACCENT="#E6007E",
    ACCENT_HOVER="#FF1493",
    ACCENT_DIM="#B80068",
    ACCENT_MUTED="#3a1028",
    ACCENT_GLOW="#2a0018",
    TEXT="#FFE6F2",
    MUTED="#D4A8BC",
    FAINT="#A07890",
    DANGER="#ff4d8d",
    DANGER_BG="#2a0014",
    DANGER_HOVER="#ff6ba3",
    SUCCESS="#FF69B4",
    ERROR="#ff5c8a",
    ACCENT_HUES=[
        "#E6007E",
        "#FF1493",
        "#FF69B4",
        "#DA70D6",
        "#C71585",
        "#F472B6",
        "#FF00CC",
    ],
)

_PRESETS["soft_neon"] = _bundle(
    id="soft_neon",
    name="Soft Neon",
    description="Same vibe, gentler button fills.",
    on_accent="#FFF5FA",
    scroll_track="#000000",
    scroll_thumb="#7A2850",
    scroll_thumb_hover="#B83280",
    BG="#000000",
    PANEL="#0a0008",
    PANEL_2="#14000e",
    PANEL_HOVER="#240016",
    BORDER="#6b2458",
    ACCENT="#B83280",
    ACCENT_HOVER="#CF3D92",
    ACCENT_DIM="#942660",
    ACCENT_MUTED="#3a1028",
    ACCENT_GLOW="#2a0018",
    TEXT="#FFE6F2",
    MUTED="#D4A8BC",
    FAINT="#A07890",
    DANGER="#ff4d8d",
    DANGER_BG="#2a0014",
    DANGER_HOVER="#ff6ba3",
    SUCCESS="#FF69B4",
    ERROR="#ff5c8a",
    ACCENT_HUES=[
        "#B83280",
        "#C43D8A",
        "#CF4894",
        "#BA5AA8",
        "#A83278",
        "#D060A0",
        "#C04090",
    ],
)

_PRESETS["violet"] = _bundle(
    id="violet",
    name="Violet Night",
    description="Purple neon — Night City alternate.",
    on_accent="#F5EEFF",
    scroll_track="#000000",
    scroll_thumb="#5A2880",
    scroll_thumb_hover="#9D4EDD",
    BG="#000000",
    PANEL="#08000f",
    PANEL_2="#100018",
    PANEL_HOVER="#1a0028",
    BORDER="#4a2868",
    ACCENT="#9D4EDD",
    ACCENT_HOVER="#C77DFF",
    ACCENT_DIM="#7B2CBF",
    ACCENT_MUTED="#2a1038",
    ACCENT_GLOW="#180028",
    TEXT="#F0E6FF",
    MUTED="#C4B0D8",
    FAINT="#9078A8",
    DANGER="#e060a0",
    DANGER_BG="#200018",
    DANGER_HOVER="#f080b8",
    SUCCESS="#b388ff",
    ERROR="#ff7090",
    ACCENT_HUES=[
        "#9D4EDD",
        "#C77DFF",
        "#B388FF",
        "#7B2CBF",
        "#A855F7",
        "#D896FF",
        "#8B5CF6",
    ],
)

_PRESETS["classic"] = _bundle(
    id="classic",
    name="Classic Slate",
    description="Matches the rest of the app — calm and neutral.",
    on_accent="#0b0d10",
    scroll_track=core_theme.BG,
    scroll_thumb=core_theme.BORDER,
    scroll_thumb_hover=core_theme.ACCENT_DIM,
    BG=core_theme.BG,
    PANEL=core_theme.PANEL,
    PANEL_2=core_theme.PANEL_2,
    PANEL_HOVER=core_theme.PANEL_HOVER,
    BORDER=core_theme.BORDER,
    ACCENT=core_theme.ACCENT,
    ACCENT_HOVER=core_theme.ACCENT_HOVER,
    ACCENT_DIM=core_theme.ACCENT_DIM,
    ACCENT_MUTED=core_theme.ACCENT_MUTED,
    ACCENT_GLOW=core_theme.ACCENT_GLOW,
    TEXT=core_theme.TEXT,
    MUTED=core_theme.MUTED,
    FAINT=core_theme.FAINT,
    DANGER=core_theme.DANGER,
    DANGER_BG=core_theme.DANGER_BG,
    DANGER_HOVER=core_theme.DANGER_HOVER,
    SUCCESS=core_theme.SUCCESS,
    ERROR=core_theme.ERROR,
    ACCENT_HUES=list(core_theme.ACCENT_HUES),
)


def list_catalog_themes() -> list[CatalogThemeBundle]:
    """Stable display order for Settings and previews."""
    order = ("neon", "soft_neon", "violet", "classic")
    return [_PRESETS[k] for k in order if k in _PRESETS]


def resolve_catalog_theme(theme_id: str | None = None) -> CatalogThemeBundle:
    tid = (theme_id or DEFAULT_CATALOG_THEME).strip()
    if tid not in _PRESETS:
        tid = DEFAULT_CATALOG_THEME
    return _PRESETS[tid]


# Back-compat: default bundle tokens (neon).
_default = resolve_catalog_theme(DEFAULT_CATALOG_THEME)
t = _default.t
ON_ACCENT = _default.on_accent
SCROLL_TRACK = _default.scroll_track
SCROLL_THUMB = _default.scroll_thumb
SCROLL_THUMB_HOVER = _default.scroll_thumb_hover
