def register(plugin_manager):
    plugin_manager.register({
        "name": "File Shredder",
        "category": "Files",
        "desc": "Securely overwrite and delete files and folders so they can't be recovered.",
        "icon": "🗑",
        "qt_page": "modules.Files.File Shredder.ui:FolderShredderModule",
    })
