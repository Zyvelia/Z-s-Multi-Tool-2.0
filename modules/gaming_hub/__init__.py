from .ui import GamingHubUI


def open_gaming_hub(manager):

    return GamingHubUI(
        manager.container,
        manager
    )


def register(plugin_manager):

    plugin_manager.register(
        {
            "name": "Gaming Hub",
            "category": "Gaming",
            "desc": "Scan, launch and manage games.",
            "icon": "🎮",
            "open": open_gaming_hub
        }
    )