from cryptography.fernet import Fernet
import os
import base64
import hashlib

from core import paths


class CryptoService:

    KEY_FILE = paths.migrate_legacy_file(
        paths.data_path("master.key"),
        "data", "master.key"
    )

    def __init__(self):

        if os.path.exists(self.KEY_FILE):

            with open(self.KEY_FILE, "rb") as f:
                self.key = f.read()

        else:

            self.key = Fernet.generate_key()

            with open(self.KEY_FILE, "wb") as f:
                f.write(self.key)

        self.cipher = Fernet(self.key)

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

    def _password_cipher(self, password):

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

        cipher = self._password_cipher(
            password
        )

        with open(filepath, "rb") as f:
            data = f.read()

        encrypted = cipher.encrypt(data)

        output_file = filepath + ".enc"

        with open(output_file, "wb") as f:
            f.write(encrypted)

        return output_file

    def decrypt_file(
        self,
        filepath,
        password
    ):

        cipher = self._password_cipher(
            password
        )

        with open(filepath, "rb") as f:
            encrypted = f.read()

        decrypted = cipher.decrypt(
            encrypted
        )

        if filepath.endswith(".enc"):
            output_file = filepath[:-4]
        else:
            output_file = filepath + ".dec"

        with open(output_file, "wb") as f:
            f.write(decrypted)

        return output_file