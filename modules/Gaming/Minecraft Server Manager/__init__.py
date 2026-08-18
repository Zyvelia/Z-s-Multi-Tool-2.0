from .ui import GameServerManagerModule, MinecraftServerManagerModule


def open_game_server_manager(manager):
    """Plugin entry point — called by catalog_page.open_tool() via plugin_manager."""
    return GameServerManagerModule(
        manager.container,
        manager,
    )


open_minecraft_server_manager = open_game_server_manager


def register(plugin_manager):
    """Self-register with core.plugin_manager.PluginManager.load_plugins()."""
    plugin_manager.register(
        {
            "name": "Game Server Manager",
            "category": "Gaming",
            "desc": (
                "Universal dedicated server manager — Minecraft Java & Bedrock, Satisfactory, "
                "Terraria, Valheim, Palworld, Project Zomboid, SteamCMD, and custom servers."
            ),
            "icon": "🖥️",
            "open": open_game_server_manager,
        }
    )
