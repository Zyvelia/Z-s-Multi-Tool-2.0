from .ui import WeatherNewsUI


def open_weather_news(manager):
    return WeatherNewsUI(
        manager.container,
        manager
    )


def register(plugin_manager):
    plugin_manager.register(
        {
            "name": "Weather & News",
            "category": "Info",
            "desc": "Live weather + custom news feeds, saved articles, and settings",
            "icon": "🌦️",
            "open": open_weather_news,
        }
    )
