def register(manager):
    manager.register({
        "name": "Media Player",
        "category": "Media",
        "desc": "VLC-powered music and video player with a SQLite-indexed library",
        "icon": "🎵",
        "qt_page": "modules.Media.Media Player.ui:MusicPage",
    })
