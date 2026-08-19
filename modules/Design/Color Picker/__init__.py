from .ui import ColorPickerModule


def register(plugin_manager):
    plugin_manager.register({
        "name": "Color Picker",
        "category": "Design",
        "desc": "Pick a color by hex/RGB/HSV or an on-screen eyedropper, and generate harmony palettes from it.",
        "icon": "🎨",
        "page_class": ColorPickerModule,
    })
