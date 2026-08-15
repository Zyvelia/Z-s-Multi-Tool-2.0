from .ui import QRGeneratorModule


def open_qr_generator(manager):
    return QRGeneratorModule(
        manager.container,
        manager
    )


def register(plugin_manager):
    plugin_manager.register(
        {
            "name": "QR Code Generator",
            "category": "Tools",
            "desc": "Turns text, URLs, Wi-Fi credentials, or contact info into a QR code you can save or share.",
            "icon": "🔳",
            "open": open_qr_generator,
        }
    )
