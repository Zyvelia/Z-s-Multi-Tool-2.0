from .ui import DuplicateFinderModule


def open_duplicate_finder(manager):
    return DuplicateFinderModule(
        manager.container,
        manager
    )


def register(plugin_manager):
    plugin_manager.register(
        {
            "name": "Duplicate File Finder",
            "category": "System",
            "desc": "Scan folders for byte-identical files and reclaim the wasted space.",
            "icon": "🧬",
            "open": open_duplicate_finder,
        }
    )
