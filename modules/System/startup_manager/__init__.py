from .ui import StartupManagerModule


def register(plugin_manager):
    plugin_manager.register({
        "name": "Startup Manager",
        "category": "System",
        "desc": "See and control everything that launches when Windows signs in.",
        "icon": "🚀",
        "page_class": StartupManagerModule,
    })
