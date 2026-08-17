from .ui import StartupManagerModule


def open_startup_manager(manager):
    return StartupManagerModule(
        manager.container,
        manager
    )


def register(plugin_manager):
    plugin_manager.register(
        {
            "name": "Startup Manager",
            "category": "System",
            "desc": "See and control everything that launches when Windows signs in.",
            "icon": "🚀",
            "open": open_startup_manager,
        }
    )
