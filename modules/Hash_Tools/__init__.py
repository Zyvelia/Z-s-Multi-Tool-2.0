def register(plugin_manager):
    plugin_manager.register({
        "name": "Hash Tools",
        "category": "Security",
        "desc": "Generate and verify hashes",
        "icon": "🔍",
        "qt_page": "modules.Hash_Tools.ui:HashToolsPage",
    })
