def register(manager):
    manager.register({
        "name": "Media Metadata Editor",
        "category": "Media",
        "desc": "Edit audio tags, image EXIF fields, and file timestamps",
        "icon": "🏷️",
        "qt_page": "modules.Media.Media Matadata Editor.ui:MetadataEditorPage",
    })
