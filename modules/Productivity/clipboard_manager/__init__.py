def register(plugin_manager):
    plugin_manager.register({
        "name": "Clipboard Manager",
        "category": "Productivity",
        "desc": "Tracks your clipboard history — search, pin, and re-copy past items.",
        "icon": "📋",
        "qt_page": "modules.Productivity.clipboard_manager.ui:ClipboardManagerModule",
    })
