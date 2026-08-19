from .ui import HashToolsPage


def register(plugin_manager):
    plugin_manager.register({
        "name": "Hash Tools",
        "category": "Security",
        "desc": "Generate and verify hashes",
        "icon": "🔍",
        "page_class": HashToolsPage,
    })
