from .ui import IconFaviconGeneratorPage


def register(plugin_manager):
    plugin_manager.register({
        "name": "Icon/Favicon Generator",
        "category": "Design",
        "desc": "Turn one image into a full favicon.ico + PNG icon set + site.webmanifest.",
        "icon": "🧩",
        "page_class": IconFaviconGeneratorPage,
    })
