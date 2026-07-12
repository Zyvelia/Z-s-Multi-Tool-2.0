from .ui import YTDownloaderPage


def open_downloader(manager):

    return YTDownloaderPage(
        manager.container,
        manager
    )


def register(plugin_manager):

    plugin_manager.register(
        {
            "name": "YT Downloader",
            "category": "Media",
            "desc": "Download YouTube videos and playlists as MP3 or MP4",
            "icon": "▶",
            "open": open_downloader
        }
    )