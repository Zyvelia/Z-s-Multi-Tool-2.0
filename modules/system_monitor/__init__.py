from .ui import SystemMonitorPage
from .mini_widget import build as build_mini_widget


def open_system_monitor(manager):

    return SystemMonitorPage(
        manager.container,
        manager
    )


def register(plugin_manager):

    plugin_manager.register(
        {
            "name": "System Monitor",
            "category": "System",
            "desc": "Live system statistics",
            "icon": "🖥️",
            "open": open_system_monitor,
            "widget": build_mini_widget
        }
    )