from .ui import DriverCheckerModule


def register(plugin_manager):
    plugin_manager.register({
        "name": "Driver/Update Checker",
        "category": "System",
        "desc": "Review installed drivers and check for driver and software updates.",
        "icon": "🔧",
        "page_class": DriverCheckerModule,
    })
