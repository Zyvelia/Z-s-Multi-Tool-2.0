from .ui import NetworkAuditorUI


def register(plugin_manager):
    plugin_manager.register({
        "name": "Network Auditor",
        "category": "Network",
        "desc": "Discover devices, scan ports, and analyze network security.",
        "icon": "🌐",
        "page_class": NetworkAuditorUI,
    })
