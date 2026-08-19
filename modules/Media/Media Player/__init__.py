from .ui import MusicPage
from .mini_widget import build as build_mini_widget


def register(manager):
    manager.register({
        "name": "Media Player",
        "category": "Media",
        "desc": "VLC-powered music and video player with a SQLite-indexed library",
        "icon": "🎵",
        "page_class": MusicPage,
        "widget": build_mini_widget,
    })
