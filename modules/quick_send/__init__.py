# modules/quick_send/__init__.py

from .ui import QuickSendPage


def open_quick_send(manager):
    return QuickSendPage(manager.container, manager)


def register(manager):
    manager.register({
        "name": "Quick Send",
        "category": "Tools",
        "desc": "Send files between your phone and this PC",
        "icon": "📤",
        "open": open_quick_send
    })
