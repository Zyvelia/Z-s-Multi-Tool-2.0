def register(plugin_manager):
    plugin_manager.register({
        "name": "File Manager",
        "category": "Files",
        "desc": "View, edit and manage any file — text, hex, images, audio, archives.",
        "icon": "📁",
        "qt_page": "modules.Files.File Manager.ui:FileViewerUI",
    })
