from .ui import GamingHubUI


def register(plugin_manager):
    plugin_manager.register({
        "name": "Gaming Hub",
        "category": "Gaming",
        "desc": "Scan, launch and manage games.",
        "icon": "🎮",
        "page_class": GamingHubUI,
    })
