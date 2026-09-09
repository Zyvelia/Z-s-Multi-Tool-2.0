def register(plugin_manager):
    plugin_manager.register({
        "name": "Network Auditor",
        "category": "Network",
        "desc": "Discover devices, scan ports, and analyze network security.",
        "icon": "🌐",
        "qt_page": "modules.Network.network_auditor.ui:NetworkAuditorUI",
    })
