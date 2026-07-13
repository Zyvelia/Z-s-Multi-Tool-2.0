# modules/mp4_to_gif/__init__.py

from .ui import Mp4ToGifPage


def open_mp4_to_gif(manager):
    return Mp4ToGifPage(manager.container, manager)


def register(manager):
    manager.register({
        "name": "MP4 to GIF",
        "category": "Media",
        "desc": "Convert video files to optimized GIFs — no command line.",
        "icon": "🎞",
        "open": open_mp4_to_gif,
    })
