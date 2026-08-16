from .ui import RemoteHubPage
from .mini_widget import build as build_mini_widget


def open_hub(manager):
    return RemoteHubPage(manager.container, manager)


def register(manager):
    manager.register({
        "name": "Remote Hub",
        "category": "Utilities",
        "desc": "One phone-friendly page linking to Music Player, Security Vault, and "
                "YouTube Downloader over Tailscale",
        "icon": "📡",
        "open": open_hub,
        "widget": build_mini_widget
    })
