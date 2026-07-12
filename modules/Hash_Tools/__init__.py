from .ui import HashToolsPage


def open_hash_tools(manager):

    return HashToolsPage(
        manager.container,
        manager
    )


def register(plugin_manager):

    plugin_manager.register(
        {
            "name": "Hash Tools",
            "category": "Security",
            "desc": "Generate and verify hashes",
            "icon": "🔍",
            "open": open_hash_tools
        }
    )