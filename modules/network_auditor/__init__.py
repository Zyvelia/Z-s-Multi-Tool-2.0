from .ui import NetworkAuditorUI


def open_network_auditor(manager):

    return NetworkAuditorUI(
        manager.container,
        manager
    )


def register(plugin_manager):

    plugin_manager.register(
        {
            "name": "Network Auditor",
            "category": "Networking",
            "desc": (
                "Discover devices, scan ports, "
                "and analyze network security."
            ),
            "icon": "🌐",
            "open": open_network_auditor
        }
    )