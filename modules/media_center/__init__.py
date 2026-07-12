from .ui import MediaCenterPage


def open_media(manager):

    return MediaCenterPage(
        manager.container,
        manager
    )


def register(plugin_manager):

    plugin_manager.register(
        {
            "name": "Media Center",
            "category": "Media",
            "desc": "Play music and videos with VLC",
            "icon": "🎬",
            "open": open_media
        }
    )