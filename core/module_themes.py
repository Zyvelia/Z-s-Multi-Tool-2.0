"""Per-module UI themes — same presets as the catalog home page."""

from pages.catalog_theme import (
    DEFAULT_CATALOG_THEME,
    CatalogThemeBundle,
    list_catalog_themes,
    resolve_catalog_theme,
)

DEFAULT_MODULE_THEME = DEFAULT_CATALOG_THEME


def list_module_themes():
    return list_catalog_themes()


def resolve_module_theme(theme_id: str | None = None) -> CatalogThemeBundle:
    return resolve_catalog_theme(theme_id)


def get_saved_module_theme(settings, module_id: str) -> str:
    themes = settings.get("module_themes") or {}
    return themes.get(module_id) or DEFAULT_MODULE_THEME


def save_module_theme(settings, module_id: str, theme_id: str) -> None:
    themes = dict(settings.get("module_themes") or {})
    themes[module_id] = theme_id
    settings.set("module_themes", themes)
