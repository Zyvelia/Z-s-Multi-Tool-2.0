def register(plugin_manager):
    plugin_manager.register({
        "name": "Gaming Hub",
        "category": "Gaming",
        "desc": "Scan, launch and manage games.",
        "icon": "🎮",
        "qt_page": "modules.Gaming.Gaming Hub.ui:GamingHubUI",
    })
