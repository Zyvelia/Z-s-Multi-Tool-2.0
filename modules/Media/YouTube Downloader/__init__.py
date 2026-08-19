from .ui import YTDownloaderPage


def register(plugin_manager):
    plugin_manager.register({
        "name": "YouTube Downloader",
        "category": "Media",
        "desc": "Download YouTube videos and playlists as MP3 or MP4",
        "icon": "▶",
        "page_class": YTDownloaderPage,
    })
