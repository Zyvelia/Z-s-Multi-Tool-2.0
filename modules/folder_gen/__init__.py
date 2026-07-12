from .ui import FolderStructureGeneratorPage


def open_folder_structure_generator(manager):
    return FolderStructureGeneratorPage(
        manager.container,
        manager
    )


def register(plugin_manager):
    plugin_manager.register(
        {
            "name": "Folder Structure Generator",
            "category": "Tools",
            "desc": "Create predefined folder structures for games from JSON templates.",
            "icon": "🗂",
            "open": open_folder_structure_generator,
        }
    )
