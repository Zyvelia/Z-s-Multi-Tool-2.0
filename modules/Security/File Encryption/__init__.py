def register(plugin_manager):
    plugin_manager.register({
        "name": "File Encryption",
        "category": "Security",
        "desc": "Encrypt and decrypt files to keep their contents private.",
        "icon": "🔒",
        "qt_page": "modules.Security.File Encryption.ui:FileEncryptorLockScreen",
    })
