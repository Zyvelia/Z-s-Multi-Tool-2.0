def register(plugin_manager):
    plugin_manager.register({
        "name": "Game Server Manager",
        "category": "Gaming",
        "desc": (
            "Universal dedicated server manager — Minecraft, Rust, ARK, CS2, Factorio, "
            "7 Days to Die, Enshrouded, V Rising, DST, Conan Exiles, Soulmask, Satisfactory, "
            "Terraria, Valheim, Palworld, Project Zomboid, SteamCMD, and custom servers."
        ),
        "icon": "🎮",
        "qt_page": "modules.Gaming.Game Server Manager.ui:GameServerManagerModule",
    })
