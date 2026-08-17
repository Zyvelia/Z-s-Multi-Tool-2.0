from .ui import IconFaviconGeneratorPage


def open_icon_generator(manager):
    return IconFaviconGeneratorPage(
        manager.container,
        manager
    )


def register(plugin_manager):
    plugin_manager.register(
        {
            "name": "Icon/Favicon Generator",
            "category": "Design",
            "desc": "Turn one image into a full favicon.ico + PNG icon set + site.webmanifest.",
            "icon": "🧩",
            "open": open_icon_generator,
        }
    )
