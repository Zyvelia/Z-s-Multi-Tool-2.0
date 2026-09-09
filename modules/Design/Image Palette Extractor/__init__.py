def register(plugin_manager):
    plugin_manager.register({
        "name": "Image Palette Extractor",
        "category": "Design",
        "desc": "Pull the dominant colors out of any image as copyable hex/RGB swatches.",
        "icon": "🖼️",
        "qt_page": "modules.Design.Image Palette Extractor.ui:ImagePaletteExtractorPage",
    })
