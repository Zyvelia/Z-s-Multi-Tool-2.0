def register(manager):
    manager.register({
        "name": "Remote Hub",
        "category": "Network",
        "desc": "One phone-friendly page linking to Music Player, Security Vault, and "
                "YouTube Downloader over Tailscale",
        "icon": "📡",
        "qt_page": "modules.Network.remote_hub.ui:RemoteHubPage",
    })
