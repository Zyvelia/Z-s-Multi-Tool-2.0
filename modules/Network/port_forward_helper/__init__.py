def register(manager):
    manager.register({
        "name": "Port Forward Helper",
        "category": "Network",
        "desc": "Detect your router via UPnP and add/remove port forwards without the admin page.",
        "icon": "🔀",
        "qt_page": "modules.Network.port_forward_helper.ui:PortForwardHelperUI",
    })
