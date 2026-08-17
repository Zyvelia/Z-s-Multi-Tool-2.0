from .ui import WeatherNewsUI


def open_game_stats_news(manager):
    return WeatherNewsUI(
        manager.container,
        manager
    )


def register(plugin_manager):
    plugin_manager.register(
        {
            "name": "Game Stats & News",
            "category": "Utilities",
            "desc": "Live game stats via your own API keys (Fortnite, Steam, or any custom API), plus custom news feeds and saved articles",
            "icon": "🕹️",
            "open": open_game_stats_news,
        }
    )
