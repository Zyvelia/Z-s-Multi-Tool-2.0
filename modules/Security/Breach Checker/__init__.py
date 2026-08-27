from .ui import BreachCheckerPage


def register(plugin_manager):
    plugin_manager.register({
        "name": "Security Center",
        "category": "Security",
        "desc": "Breach checks (HIBP) + vault password audit — weak, reused, and leaked passwords.",
        "icon": "🛡",
        "page_class": BreachCheckerPage,
    })
