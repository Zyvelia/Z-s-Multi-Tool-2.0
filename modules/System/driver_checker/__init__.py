from .ui import DriverCheckerModule


def open_driver_checker(manager):
    return DriverCheckerModule(
        manager.container,
        manager
    )


def register(plugin_manager):
    plugin_manager.register(
        {
            "name": "Driver/Update Checker",
            "category": "System",
            "desc": "Review installed drivers and check for driver and software updates.",
            "icon": "🔧",
            "open": open_driver_checker,
        }
    )
