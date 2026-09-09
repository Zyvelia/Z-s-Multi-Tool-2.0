def register(plugin_manager):
    plugin_manager.register({
        "name": "Security Center",
        "category": "Security",
        "desc": "Breach checks (HIBP) + vault password audit — weak, reused, and leaked passwords.",
        "icon": "🛡",
        "qt_page": "modules.Security.Breach Checker.ui:BreachCheckerPage",
    })
