# modules/notes/__init__.py

from .ui import NotesPage


def open_notes(manager):
    return NotesPage(manager.container, manager)


def register(manager):
    manager.register({
        "name": "Notes",
        "category": "Utilities",
        "desc": "Free-form notes with attached links",
        "icon": "📝",
        "open": open_notes
    })
