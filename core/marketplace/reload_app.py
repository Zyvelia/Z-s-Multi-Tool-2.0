"""Reload plugins and drop cached Qt pages after a marketplace change."""

from __future__ import annotations

import importlib
import sys


def forget_module_imports(relpath: str | None):
    if not relpath:
        return
    dotted = "modules." + relpath.replace("\\", "/").replace("/", ".")
    prefix = dotted + "."
    for key in list(sys.modules):
        if key == dotted or key.startswith(prefix):
            del sys.modules[key]


def apply_to_app(page_manager, changed_relpaths: list[str] | None = None, changed_names: list[str] | None = None):
    importlib.invalidate_caches()
    for rel in changed_relpaths or []:
        forget_module_imports(rel)
    page_manager.plugin_manager.reload()

    names = list(changed_names or [])
    current = page_manager.current_name
    if current in names:
        page_manager.show_page("catalog")

    window = getattr(page_manager, "window", None)
    host = getattr(window, "qt_tool_host", None) if window is not None else None
    for name in names:
        page = page_manager.pages.pop(name, None)
        if page is None:
            continue
        if host is not None and host.indexOf(page) >= 0:
            host.removeWidget(page)
        page.deleteLater()

    catalog = page_manager.pages.get("catalog")
    if catalog is not None:
        catalog._build_pills()
        catalog.render()
    settings = page_manager.pages.get("settings")
    if settings is not None and hasattr(settings, "_refresh_tools_list"):
        settings._refresh_tools_list()
