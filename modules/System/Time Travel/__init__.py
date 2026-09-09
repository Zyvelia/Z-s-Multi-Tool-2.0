def register(plugin_manager):
    plugin_manager.register({
        "name": "Time Travel",
        "category": "System",
        "desc": "Timeline of GSM backups, save zips, AppData files, and Windows VSS shadows.",
        "icon": "⏪",
        "qt_page": "modules.System.Time Travel.ui:TimeTravelPage",
    })
