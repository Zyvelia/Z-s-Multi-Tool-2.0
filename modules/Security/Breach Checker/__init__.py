from .ui import BreachCheckerPage


def open_breach_checker(manager):

    return BreachCheckerPage(
        manager.container,
        manager
    )


def register(plugin_manager):

    plugin_manager.register(
        {
            "name": "Breach Checker",
            "category": "Security",
            "desc": "Check passwords and email addresses against known data breaches (HaveIBeenPwned)",
            "icon": "🕵️",
            "open": open_breach_checker
        }
    )
