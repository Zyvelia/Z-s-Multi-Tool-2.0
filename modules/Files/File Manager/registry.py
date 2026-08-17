"""
registry.py — Registration helper for Universal File Viewer.
Can be imported standalone to register the tool without importing the full UI.
"""

from __future__ import annotations

from .module import (
    MODULE_NAME, MODULE_DESC, MODULE_ICON, MODULE_CATEGORY,
)


def register(plugin_manager) -> None:
    """
    Register the Universal File Viewer tool with the application's plugin manager.
    Called automatically by __init__.py when the module package is imported.
    """
    from .viewer import FileViewerUI

    def _open(manager):
        return FileViewerUI(manager.container, manager)

    plugin_manager.register(
        {
            "name":     MODULE_NAME,
            "category": MODULE_CATEGORY,
            "desc":     MODULE_DESC,
            "icon":     MODULE_ICON,
            "open":     _open,
        }
    )
