def register(plugin_manager):
    plugin_manager.register({
        "name": "Folder Generator",
        "category": "Files",
        "desc": "Create predefined folder structures for games from JSON templates.",
        "icon": "🗂",
        "qt_page": "modules.Files.Folder Generator.ui:FolderStructureGeneratorPage",
    })
