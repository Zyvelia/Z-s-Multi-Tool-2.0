from .ui import RemoteHubPage


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
    })
