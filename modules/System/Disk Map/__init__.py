def register(plugin_manager):
    plugin_manager.register({
        "name": "Disk Map",
        "category": "System",
        "desc": "See which folders are eating a drive — biggest first, click to go in.",
        "icon": "🗺",
        "qt_page": "modules.System.Disk Map.ui:DiskMapPage",
    })
