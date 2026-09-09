def register(manager):
    manager.register({
        "name": "Quick Send",
        "category": "Network",
        "desc": "Send files between your phone and this PC",
        "icon": "📤",
        "qt_page": "modules.Network.quick_send.ui:QuickSendPage",
    })
