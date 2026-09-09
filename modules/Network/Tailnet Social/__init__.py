def register(plugin_manager):
    plugin_manager.register({
        "name": "Tailnet Social",
        "category": "Network",
        "desc": "Invite keys for friends: shared jukebox queue, soundboard, optional limited server console.",
        "icon": "🟠",
        "qt_page": "modules.Network.Tailnet Social.ui:TailnetSocialPage",
    })
