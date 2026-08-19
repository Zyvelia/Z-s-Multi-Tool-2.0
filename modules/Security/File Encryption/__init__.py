from .lock_screen import FileEncryptorLockScreen


def register(plugin_manager):
    plugin_manager.register({
        "name": "File Encryption",
        "category": "Security",
        "desc": "Encrypt and decrypt files to keep their contents private.",
        "icon": "🔒",
        "page_class": FileEncryptorLockScreen,
    })
