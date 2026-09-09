def register(plugin_manager):
    plugin_manager.register({
        "name": "Driver/Update Checker",
        "category": "System",
        "desc": "Review installed drivers and check for driver and software updates.",
        "icon": "🔧",
        "qt_page": "modules.System.driver_checker.ui:DriverCheckerModule",
    })
