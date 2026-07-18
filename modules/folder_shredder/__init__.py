from .ui import FolderShredderModule


def open_folder_shredder(manager):
    return FolderShredderModule(
        manager.container,
        manager
    )


def register(plugin_manager):
    plugin_manager.register(
        {
            "name": "Folder Shredder",
            "category": "Tools",
            "desc": "Securely overwrite and delete files and folders so they can't be recovered.",
            "icon": "🗑",
            "open": open_folder_shredder,
        }
    )
