from .ui import FolderShredderModule


def register(plugin_manager):
    plugin_manager.register({
        "name": "File Shredder",
        "category": "Files",
        "desc": "Securely overwrite and delete files and folders so they can't be recovered.",
        "icon": "🗑",
        "page_class": FolderShredderModule,
    })
