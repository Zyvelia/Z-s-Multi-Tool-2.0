from .ui import DuplicateFinderModule


def register(plugin_manager):
    plugin_manager.register({
        "name": "Duplicate File Finder",
        "category": "System",
        "desc": "Scan folders for byte-identical files and reclaim the wasted space.",
        "icon": "🧬",
        "page_class": DuplicateFinderModule,
    })
