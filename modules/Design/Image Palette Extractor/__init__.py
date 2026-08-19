from .ui import ImagePaletteExtractorPage


def register(plugin_manager):
    plugin_manager.register({
        "name": "Image Palette Extractor",
        "category": "Design",
        "desc": "Pull the dominant colors out of any image as copyable hex/RGB swatches.",
        "icon": "🖼️",
        "page_class": ImagePaletteExtractorPage,
    })
