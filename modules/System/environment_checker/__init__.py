def register(plugin_manager):
    plugin_manager.register({
        "name": "Environment Checker",
        "category": "System",
        "desc": "See what's installed for this app — VLC, Tailscale, WebView2, and more.",
        "icon": "🩺",
        "qt_page": "modules.System.environment_checker.ui:EnvironmentCheckerPage",
    })
