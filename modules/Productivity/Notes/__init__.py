def register(manager):
    manager.register({
        "name": "Notes",
        "category": "Productivity",
        "desc": "Free-form notes with attached links",
        "icon": "📝",
        "qt_page": "modules.Productivity.Notes.ui:NotesPage",
    })
