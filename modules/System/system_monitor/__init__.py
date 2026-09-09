def register(plugin_manager):
    plugin_manager.register({
        "name": "System Monitor",
        "category": "System",
        "desc": "Live system statistics",
        "icon": "🖥️",
        "qt_page": "modules.System.system_monitor.ui:SystemMonitorPage",
    })
