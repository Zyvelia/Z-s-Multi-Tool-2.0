from .ui import SoundboardPage


def open_soundboard(manager):

    return SoundboardPage(
        manager.container,
        manager
    )


def register(plugin_manager):

    plugin_manager.register(
        {
            "name": "Soundboard",
            "category": "Media",
            "desc": "Play sounds through your mic or audio device",
            "icon": "🔊",
            "open": open_soundboard
        }
    )