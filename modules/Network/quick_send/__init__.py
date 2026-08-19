from .ui import QuickSendPage


def register(manager):
    manager.register({
        "name": "Quick Send",
        "category": "Network",
        "desc": "Send files between your phone and this PC",
        "icon": "📤",
        "page_class": QuickSendPage,
    })
