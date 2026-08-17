from .ui import ColorPickerModule


def open_color_picker(manager):
    return ColorPickerModule(
        manager.container,
        manager
    )


def register(plugin_manager):
    plugin_manager.register(
        {
            "name": "Color Picker",
            "category": "Design",
            "desc": "Pick a color by hex/RGB/HSV or an on-screen eyedropper, and generate harmony palettes from it.",
            "icon": "🎨",
            "open": open_color_picker,
        }
    )
