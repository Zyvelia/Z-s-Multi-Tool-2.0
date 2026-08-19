from .ui import SoundboardPage


def register(plugin_manager):
    plugin_manager.register({
        "name": "Soundboard",
        "category": "Media",
        "desc": "Play sounds through your mic or audio device",
        "icon": "🔊",
        "page_class": SoundboardPage,
    })
