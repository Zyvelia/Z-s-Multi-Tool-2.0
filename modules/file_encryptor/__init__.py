from .lock_screen import FileEncryptorLockScreen


def open_encryptor(manager):

    return FileEncryptorLockScreen(
        manager.container,
        manager
)


def register(plugin_manager):

    plugin_manager.register(
        {
            "name": "File Encryptor",
            "category": "Security",
            "desc": "Encrypt and decrypt files",
            "icon": "🔒",
            "open": open_encryptor
        }
    )