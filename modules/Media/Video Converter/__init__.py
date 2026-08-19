from .ui import Mp4ToGifPage


def register(manager):
    manager.register({
        "name": "Video to GIF Converter",
        "category": "Media",
        "desc": "Convert video files to optimized GIFs — no command line.",
        "icon": "🎞",
        "page_class": Mp4ToGifPage,
    })
