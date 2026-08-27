from .ui import MangaDexPage
from .mini_widget import build as build_mini_widget


def register(manager):
    manager.register({
        "name": "MangaDex Reader",
        "category": "Media",
        "desc": "Search, read, and download manga chapters from MangaDex (api.mangadex.org)",
        "icon": "📖",
        "page_class": MangaDexPage,
        "widget": build_mini_widget,
    })
