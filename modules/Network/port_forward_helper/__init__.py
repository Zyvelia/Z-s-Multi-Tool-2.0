# modules/Network/port_forward_helper/__init__.py

from .ui import PortForwardHelperUI


def open_port_forward_helper(manager):
    return PortForwardHelperUI(manager.container, manager)


def register(manager):
    manager.register({
        "name": "Port Forward Helper",
        "category": "Network",
        "desc": "Detect your router via UPnP and add/remove port forwards without the admin page.",
        "icon": "🔀",
        "open": open_port_forward_helper
    })
