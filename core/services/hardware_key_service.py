"""
Optional FIDO2 / security-key unlock for Secure Vault.

Requires the `fido2` package and a USB security key (YubiKey, etc.).
Unlock still uses the same session lock as the master password — it is an
alternative way to unlock the app, not a replacement for the master password
when registering or disabling the key.
"""

from __future__ import annotations

import base64
import secrets
from typing import Any

RP_ID = "localhost"
RP_NAME = "Z's Multi Tool Vault"
ORIGIN = f"https://{RP_ID}"


class HardwareKeyError(Exception):
    pass


class HardwareKeyService:

    def __init__(self, auth_service):
        self.auth = auth_service
        self._register_state = None
        self._auth_state = None

    # ----------------------------------------------------- availability

    @staticmethod
    def library_available() -> bool:
        try:
            import fido2  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def device_detected() -> bool:
        if not HardwareKeyService.library_available():
            return False
        try:
            from fido2.hid import CtapHidDevice
            return bool(list(CtapHidDevice.list_devices()))
        except Exception:
            return False

    def status_message(self) -> str:
        if not self.library_available():
            return "Install the fido2 package to use a security key (pip install fido2)."
        if not self.device_detected():
            return "Plug in a FIDO2 security key (YubiKey, etc.), then try again."
        if self.is_enabled():
            return "Security key unlock is enabled for this vault."
        return "Security key detected — you can register it below."

    # ----------------------------------------------------- config

    def _load_config(self) -> dict[str, Any]:
        data = self.auth._load()
        return dict(data.get("hardware_key") or {})

    def _save_config(self, cfg: dict[str, Any]) -> None:
        data = self.auth._load()
        data["hardware_key"] = cfg
        self.auth._save(data)

    def is_enabled(self) -> bool:
        cfg = self._load_config()
        return bool(cfg.get("enabled") and cfg.get("credential_b64"))

    def disable(self) -> None:
        self._save_config({"enabled": False})

    def _load_credential(self):
        cfg = self._load_config()
        raw = cfg.get("credential_b64")
        if not raw:
            return None
        from fido2.webauthn import AttestedCredentialData
        return AttestedCredentialData(base64.b64decode(raw))

    def _store_credential(self, credential, *, enabled: bool = True) -> None:
        self._save_config({
            "enabled": enabled,
            "credential_b64": base64.b64encode(bytes(credential)).decode("ascii"),
        })

    # ----------------------------------------------------- fido2 helpers

    def _server(self):
        from fido2.server import Fido2Server
        from fido2.webauthn import PublicKeyCredentialRpEntity
        return Fido2Server(PublicKeyCredentialRpEntity(id=RP_ID, name=RP_NAME))

    def _client(self):
        from fido2.hid import CtapHidDevice
        from fido2.client import Fido2Client
        devices = list(CtapHidDevice.list_devices())
        if not devices:
            raise HardwareKeyError("No security key detected. Plug in your key and try again.")
        return Fido2Client(devices[0], ORIGIN)

    @staticmethod
    def _user_verification_preferred():
        from fido2.webauthn import UserVerificationRequirement
        return UserVerificationRequirement.PREFERRED

    @staticmethod
    def _client_make_credential(client, options):
        try:
            return client.make_credential(options)
        except TypeError:
            return client.make_credential({"publicKey": options})

    @staticmethod
    def _client_get_assertion(client, options):
        try:
            selection = client.get_assertion(options)
        except TypeError:
            selection = client.get_assertion({"publicKey": options})
        if hasattr(selection, "get_response"):
            return selection.get_response(0)
        return selection

    # ----------------------------------------------------- register / unlock

    def register_key(self) -> None:
        if not self.library_available():
            raise HardwareKeyError("The fido2 package is not installed.")
        if not self.device_detected():
            raise HardwareKeyError("No security key detected.")

        from fido2.webauthn import PublicKeyCredentialUserEntity

        server = self._server()
        client = self._client()
        user = PublicKeyCredentialUserEntity(
            id=secrets.token_bytes(16),
            name="vault-user",
            display_name="Secure Vault",
        )
        options, state = server.register_begin(
            user,
            user_verification=self._user_verification_preferred(),
        )
        self._register_state = state

        att = self._client_make_credential(client, options)
        auth_data = server.register_complete(self._register_state, att)
        self._register_state = None

        credential = getattr(auth_data, "credential_data", None) or auth_data
        self._store_credential(credential, enabled=True)

    def verify_and_unlock(self) -> bool:
        if not self.is_enabled():
            raise HardwareKeyError("Security key unlock is not enabled.")

        credential = self._load_credential()
        if credential is None:
            raise HardwareKeyError("No registered security key found.")

        server = self._server()
        client = self._client()
        options, state = server.authenticate_begin(
            [credential],
            user_verification=self._user_verification_preferred(),
        )
        self._auth_state = state

        assertion = self._client_get_assertion(client, options)
        server.authenticate_complete(self._auth_state, [credential], assertion)
        self._auth_state = None

        self.auth.unlock()
        return True
