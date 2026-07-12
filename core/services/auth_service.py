import os
import json
import hashlib
import time # Added for auto-lock functionality

from core import paths


class AuthService:

    FILE = paths.migrate_legacy_file(
        paths.data_path("vault_settings.json"),
        "data", "vault_settings.json"
    )

    def __init__(self):

        if not os.path.exists(self.FILE):

            with open(self.FILE, "w") as f:
                json.dump(
                    {
                        "initialized": False,
                        "master_password": ""
                    },
                    f,
                    indent=4
                )

        # Initialize auto-lock properties
        self.last_activity = time.time()
        self.locked = False
        self.LOCK_TIMEOUT = 300 # Default auto-lock timeout in seconds (5 minutes)

    # =====================================================
    # INTERNAL
    # =====================================================

    def _load(self):

        with open(self.FILE, "r") as f:
            return json.load(f)

    def _save(self, data):

        with open(self.FILE, "w") as f:
            json.dump(data, f, indent=4)

    def _hash(self, password):

        return hashlib.sha256(
            password.encode()
        ).hexdigest()

    # =====================================================
    # AUTO-LOCK METHODS
    # =====================================================

    def touch(self):
        """
        Updates the last activity timestamp to the current time.
        """
        self.last_activity = time.time()

    def is_locked(self):
        """
        Checks if the vault should be locked due to inactivity or explicit lock.
        """
        if self.locked:
            return True
        
        # Check for auto-lock due to inactivity
        if time.time() - self.last_activity > self.LOCK_TIMEOUT:
            self.locked = True # Explicitly set to locked if timeout occurs
            return True
            
        return False

    def lock(self):
        """
        Explicitly locks the vault.
        """
        self.locked = True

    def unlock(self):
        """
        Unlocks the vault and updates the last activity timestamp.
        """
        self.locked = False
        self.touch() # Reset activity timer upon unlock


    # =====================================================
    # STATUS
    # =====================================================

    def is_initialized(self):

        data = self._load()

        return data.get(
            "initialized",
            False
        )

    # =====================================================
    # MASTER PASSWORD
    # =====================================================

    def create_master_password(
        self,
        password
    ):

        data = self._load()

        data["initialized"] = True
        data["master_password"] = self._hash(
            password
        )

        self._save(data)

    def verify_master_password(
        self,
        password
    ):

        data = self._load()

        # Unlock and touch on successful verification
        if self._hash(password) == data.get("master_password", ""):
            self.unlock()
            return True
        return False

    def change_master_password(
        self,
        old_password,
        new_password
    ):

        if not self.verify_master_password(
            old_password
        ):
            return False

        data = self._load()

        data["master_password"] = self._hash(
            new_password
        )

        self._save(data)
        self.touch() # Update activity after changing password
        return True