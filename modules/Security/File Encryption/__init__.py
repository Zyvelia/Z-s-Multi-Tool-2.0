from .lock_screen import FileEncryptorLockScreen


def open_encryptor(manager):

    return FileEncryptorLockScreen(
        manager.container,
        manager
)


def register(plugin_manager):

    plugin_manager.register(
        {
            "name": "File Encryption",
            "category": "Security",
            "desc": "Encrypt and decrypt files to keep their contents private.",
            "icon": "🔒",
            "open": open_encryptor
        }
    )