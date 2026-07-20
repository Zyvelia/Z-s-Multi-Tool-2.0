# modules/metadata_editor/__init__.py

from .ui import MetadataEditorPage


def open_metadata_editor(manager):
    # manager.container is your actual CTk root/app
    return MetadataEditorPage(manager.container, manager)


def register(manager):
    manager.register({
        "name": "Metadata Editor",
        "category": "Utilities",
        "desc": "Edit audio tags, image EXIF fields, and file timestamps",
        "icon": "🏷️",
        "open": open_metadata_editor,
    })
