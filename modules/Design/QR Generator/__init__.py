from .ui import QRGeneratorModule


def register(plugin_manager):
    plugin_manager.register({
        "name": "QR Generator",
        "category": "Utilities",
        "desc": "Turns text, URLs, Wi-Fi credentials, or contact info into a QR code you can save or share.",
        "icon": "🔳",
        "page_class": QRGeneratorModule,
    })
