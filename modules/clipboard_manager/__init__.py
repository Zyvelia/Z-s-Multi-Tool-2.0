from .ui import ClipboardManagerModule


def open_clipboard_manager(manager):
    return ClipboardManagerModule(
        manager.container,
        manager
    )


def register(plugin_manager):
    plugin_manager.register(
        {
            "name": "Clipboard Manager",
            "category": "Tools",
            "desc": "Tracks your clipboard history — search, pin, and re-copy past items.",
            "icon": "📋",
            "open": open_clipboard_manager,
        }
    )
