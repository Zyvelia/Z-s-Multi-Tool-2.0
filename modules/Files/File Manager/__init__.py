from .viewer import FileViewerUI


def open_file_viewer(manager):
    return FileViewerUI(
        manager.container,
        manager
    )


def register(plugin_manager):
    plugin_manager.register(
        {
            "name": "File Manager",
            "category": "Files",
            "desc": "View, edit and manage any file — text, hex, images, audio, archives.",
            "icon": "📁",
            "open": open_file_viewer,
        }
    )
