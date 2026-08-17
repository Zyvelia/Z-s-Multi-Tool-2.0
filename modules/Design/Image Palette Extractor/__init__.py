from .ui import ImagePaletteExtractorPage


def open_palette_extractor(manager):
    return ImagePaletteExtractorPage(
        manager.container,
        manager
    )


def register(plugin_manager):
    plugin_manager.register(
        {
            "name": "Image Palette Extractor",
            "category": "Design",
            "desc": "Pull the dominant colors out of any image as copyable hex/RGB swatches.",
            "icon": "🖼️",
            "open": open_palette_extractor,
        }
    )
