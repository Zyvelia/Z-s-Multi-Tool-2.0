from .lock_screen import PasswordVaultLockScreen


def open_vault(manager):
    return PasswordVaultLockScreen(
        manager.container,
        manager
    )


def register(plugin_manager):

    plugin_manager.register({
        "name": "Password Vault",
        "category": "Utilities",
        "desc": "Encrypted password manager",
        "icon": "🔐",
        "open": open_vault
    })