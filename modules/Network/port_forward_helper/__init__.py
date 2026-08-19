from .ui import PortForwardHelperUI


def register(manager):
    manager.register({
        "name": "Port Forward Helper",
        "category": "Network",
        "desc": "Detect your router via UPnP and add/remove port forwards without the admin page.",
        "icon": "🔀",
        "page_class": PortForwardHelperUI,
    })
