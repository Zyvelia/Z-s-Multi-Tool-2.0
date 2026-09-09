def register(plugin_manager):
    plugin_manager.register({
        "name": "Save Editor",
        "category": "Files",
        "desc": "Open, inspect, and edit game save files — JSON, XML, YAML, INI, "
                "compressed/encoded/encrypted saves, and any unrecognized binary save "
                "(readable-text view, value search, and custom named-field layouts).",
        "icon": "💾",
        "qt_page": "modules.Files.Save Editor.ui:SaveEditorModule",
    })
