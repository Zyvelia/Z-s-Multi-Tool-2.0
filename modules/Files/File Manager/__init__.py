from .viewer import FileViewerUI


def register(plugin_manager):
    plugin_manager.register({
        "name": "File Manager",
        "category": "Files",
        "desc": "View, edit and manage any file — text, hex, images, audio, archives.",
        "icon": "📁",
        "page_class": FileViewerUI,
    })
