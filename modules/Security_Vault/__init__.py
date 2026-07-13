from .lock_screen import PasswordVaultLockScreen


def open_security_vault(manager):
    return PasswordVaultLockScreen(
        manager.container,
        manager
    )


def register(plugin_manager):

    plugin_manager.register({
        "name": "Security Vault",
        "category": "Utilities",
        "desc": "Encrypted passwords and authenticator (2FA) codes, in one place.",
        "icon": "🔐",
        "open": open_security_vault
    })