from .ui import AppInstallerModule


def open_app_installer(manager):
    return AppInstallerModule(
        manager.container,
        manager
    )


def register(plugin_manager):
    plugin_manager.register(
        {
            "name": "App Installer",
            "category": "Utilities",
            "desc": "Search and install apps via winget, or run your own custom install commands.",
            "icon": "📦",
            "open": open_app_installer,
        }
    )