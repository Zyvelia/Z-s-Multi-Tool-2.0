from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
import os
import base64
import hashlib

from core import paths


class CryptoService:

    KEY_FILE = paths.migrate_legacy_file(
        paths.data_path("master.key"),
        "data", "master.key"
    )

    # Iterations for the password-based KDF used on ad-hoc file exports.
    # Same OWASP-recommended floor as AuthService's master-password hash.
    PBKDF2_ITERATIONS = 600_000
    SALT_BYTES = 16

    def __init__(self):

        if os.path.exists(self.KEY_FILE):

            with open(self.KEY_FILE, "rb") as f:
                self.key = f.read()

        else:

            self.key = Fernet.generate_key()

            with open(self.KEY_FILE, "wb") as f:
                f.write(self.key)

        self._harden_key_file_permissions()

        self.cipher = Fernet(self.key)

    def _harden_key_file_permissions(self):
        """Restrict master.key to the owning user only, best-effort."""
        try:
            os.chmod(self.KEY_FILE, 0o600)
        except Exception:
            pass

    def encrypt(self, text):

        return self.cipher.encrypt(
            text.encode()
        ).decode()

    def decrypt(self, text):

        return self.cipher.decrypt(
            text.encode()
        ).decode()

    # =====================================================
    # FILE PASSWORD KEY
    # =====================================================
    # Previously this derived the Fernet key via a single, unsalted
    # SHA-256 of the password — the same password always produced the
    # same key, with no stretching, so a stolen .enc file could be
    # attacked with a plain dictionary/rainbow-table run at GPU speed.
    # Now a random salt is generated per encryption and stored alongside
    # the ciphertext (it's not secret — only the password is), and the
    # key is derived with PBKDF2-HMAC-SHA256 at a high iteration count,
    # which makes each password guess computationally expensive.

    def _derive_key(self, password, salt):

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=self.PBKDF2_ITERATIONS,
        )

        return base64.urlsafe_b64encode(
            kdf.derive(password.encode())
        )

    def _legacy_password_cipher(self, password):
        """Old unsalted derivation, kept only to decrypt files created
        before this change (see decrypt_file's fallback)."""

        key = base64.urlsafe_b64encode(
            hashlib.sha256(
                password.encode()
            ).digest()
        )

        return Fernet(key)

    # =====================================================
    # FILE ENCRYPTION
    # =====================================================

    def encrypt_file(
        self,
        filepath,
        password
    ):

        salt = os.urandom(self.SALT_BYTES)
        cipher = Fernet(self._derive_key(password, salt))

        with open(filepath, "rb") as f:
            data = f.read()

        encrypted = cipher.encrypt(data)

        output_file = filepath + ".enc"

        # Prepend the salt (fixed-width, not secret) so decrypt_file can
        # re-derive the same key from the password alone.
        with open(output_file, "wb") as f:
            f.write(salt)
            f.write(encrypted)

        return output_file

    def decrypt_file(
        self,
        filepath,
        password
    ):

        with open(filepath, "rb") as f:
            blob = f.read()

        salt, encrypted = blob[:self.SALT_BYTES], blob[self.SALT_BYTES:]
        cipher = Fernet(self._derive_key(password, salt))

        try:
            decrypted = cipher.decrypt(encrypted)
        except InvalidToken:
            # Fall back to the legacy unsalted format for files encrypted
            # before this change (whole blob was the Fernet token, no
            # salt prefix).
            legacy_cipher = self._legacy_password_cipher(password)
            decrypted = legacy_cipher.decrypt(blob)

        if filepath.endswith(".enc"):
            output_file = filepath[:-4]
        else:
            output_file = filepath + ".dec"

        with open(output_file, "wb") as f:
            f.write(decrypted)

        return output_file