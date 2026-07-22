from .ui import MusicPage
from .mini_widget import build as build_mini_widget


def open_music(manager):
    # manager.container is your actual CTk root/app
    return MusicPage(manager.container, manager)


def register(manager):
    manager.register({
        "name": "Music & Video Player",
        "category": "Media",
        "desc": "VLC-powered music and video player with a SQLite-indexed library",
        "icon": "🎵",
        "open": open_music,
        "widget": build_mini_widget
    })