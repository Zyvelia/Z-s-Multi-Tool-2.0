def register(manager):
    manager.register({
        "name": "Messages",
        "category": "Productivity",
        "desc": "Chat with your paired phone(s) over Tailscale",
        "icon": "💬",
        "qt_page": "modules.Productivity.Messaging.ui:MessagingPage",
    })
