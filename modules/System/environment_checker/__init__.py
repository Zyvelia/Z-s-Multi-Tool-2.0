from .ui import EnvironmentCheckerPage


def register(plugin_manager):
    plugin_manager.register({
        "name": "Environment Checker",
        "category": "System",
        "desc": "See what's installed for this app — VLC, Tailscale, WebView2, and more.",
        "icon": "🩺",
        "page_class": EnvironmentCheckerPage,
    })
