from .ui import UpdateManagerPage


def open_update_manager(manager):
    return UpdateManagerPage(
        manager.container,
        manager
    )


def register(plugin_manager):
    plugin_manager.register(
        {
            "name": "Update Manager",
            "category": "Tools",
            "desc": "Block or pause Windows Update, and view/uninstall installed updates.",
            "icon": "🛡",
            "open": open_update_manager,
        }
    )
