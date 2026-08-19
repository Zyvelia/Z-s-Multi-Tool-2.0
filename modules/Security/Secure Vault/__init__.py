from .lock_screen import PasswordVaultLockScreen


def register(plugin_manager):
    plugin_manager.register({
        "name": "Secure Vault",
        "category": "Security",
        "desc": "Encrypted passwords and authenticator (2FA) codes, in one place.",
        "icon": "🔐",
        "page_class": PasswordVaultLockScreen,
    })
