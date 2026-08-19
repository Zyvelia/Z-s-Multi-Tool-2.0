from .ui import NotesPage


def register(manager):
    manager.register({
        "name": "Notes",
        "category": "Productivity",
        "desc": "Free-form notes with attached links",
        "icon": "📝",
        "page_class": NotesPage,
    })
