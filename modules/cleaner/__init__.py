from .ui import CleanerPage


def open_cleaner(manager):
    return CleanerPage(
        manager.container,
        manager
    )


def register(plugin_manager):
    plugin_manager.register(
        {
            "name": "Cleaner",
            "category": "Tools",
            "desc": "Scan and delete temp files, caches, and other junk.",
            "icon": "🧹",
            "open": open_cleaner,
        }
    )
