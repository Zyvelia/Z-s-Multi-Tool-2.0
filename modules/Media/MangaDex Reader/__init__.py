def register(manager):
    manager.register({
        "name": "MangaDex Reader",
        "category": "Media",
        "desc": "Search, read, and download MangaDex chapters. OCR + voice + translate on the page for untranslated scans.",
        "icon": "📖",
        "qt_page": "modules.Media.MangaDex Reader.ui:MangaDexPage",
    })
