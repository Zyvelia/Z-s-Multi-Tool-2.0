def register(plugin_manager):
    plugin_manager.register({
        "name": "SSH / Serial",
        "category": "Network",
        "desc": "SSH into a box or open a COM serial console from this app.",
        "icon": "🖥",
        "qt_page": "modules.Network.SSH Serial.ui:SSHSerialPage",
    })
