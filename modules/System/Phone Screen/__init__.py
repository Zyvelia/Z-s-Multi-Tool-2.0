def register(plugin_manager):
    plugin_manager.register({
        "name": "Phone Screen",
        "category": "System",
        "desc": "Mirror an Android phone or emulator with tap and swipe — USB or wireless ADB.",
        "icon": "📱",
        "qt_page": "modules.System.Phone Screen.ui:PhoneScreenPage",
    })
