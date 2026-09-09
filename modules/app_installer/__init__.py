def register(plugin_manager):
    plugin_manager.register({
        "name": "App Installer",
        "category": "Utilities",
        "desc": "Search and install apps via winget, or run your own custom install commands.",
        "icon": "📦",
        "qt_page": "modules.app_installer.ui:AppInstallerModule",
    })
