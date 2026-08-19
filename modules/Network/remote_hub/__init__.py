from .ui import RemoteHubPage
from .mini_widget import build as build_mini_widget


def register(manager):
    manager.register({
        "name": "Remote Hub",
        "category": "Network",
        "desc": "One phone-friendly page linking to Music Player, Security Vault, and "
                "YouTube Downloader over Tailscale",
        "icon": "📡",
        "page_class": RemoteHubPage,
        "widget": build_mini_widget,
    })
