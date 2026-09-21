def register(plugin_manager):
    plugin_manager.register({
        "name": "Hello Module",
        "category": "Utilities",
        "desc": "A simple example module for Z's Multi Tool.",
        "icon": "👋",
        "qt_page": "modules.Hello_Module.ui:HelloModulePage",
    })
