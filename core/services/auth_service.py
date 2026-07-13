import os
import json
import hmac
import base64
import hashlib
import secrets
import time # Added for auto-lock functionality

from core import paths


class AuthService:

    FILE = paths.migrate_legacy_file(
        paths.data_path("vault_settings.json"),
        "data", "vault_settings.json"
    )

    # PBKDF2-HMAC-SHA256 iteration count. 600,000 is the current OWASP
    # baseline (2023 guidance) for PBKDF2-SHA256 — high enough to make
    # offline brute-forcing of a stolen vault_settings.json expensive,
    # while still taking a human-imperceptible ~50-100ms to verify.
    PBKDF2_ITERATIONS = 600_000
    SALT_BYTES = 16

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

        self._harden_file_permissions()

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

        self._harden_file_permissions()

    def _harden_file_permissions(self):
        """
        Restrict vault_settings.json to the owning user only (rw-------).
        No-op (best effort) on platforms/filesystems that don't support
        POSIX permission bits, e.g. some Windows filesystems.
        """
        try:
            os.chmod(self.FILE, 0o600)
        except Exception:
            pass

    # -------------------------------------------------
    # Password hashing: salted PBKDF2-HMAC-SHA256
    # -------------------------------------------------
    # Stored format: "pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>"
    # A random salt per-vault defeats precomputed rainbow tables, and the
    # iteration count makes each guess expensive for an offline attacker
    # (unlike a single unsalted SHA-256 call, which a modern GPU can test
    # billions of times per second).

    def _hash(self, password, salt=None, iterations=None):

        if salt is None:
            salt = secrets.token_bytes(self.SALT_BYTES)
        if iterations is None:
            iterations = self.PBKDF2_ITERATIONS

        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            salt,
            iterations
        )

        return "pbkdf2_sha256${}${}${}".format(
            iterations,
            base64.b64encode(salt).decode(),
            base64.b64encode(digest).decode()
        )

    def _verify_hash(self, password, stored):
        """
        Verifies a password against a stored hash. Transparently supports
        the legacy unsalted-SHA256 format so existing vaults keep working;
        callers should re-hash and re-save on a successful legacy match
        (see verify_master_password) to upgrade the vault in place.
        """

        if stored.startswith("pbkdf2_sha256$"):
            try:
                _, iterations, salt_b64, hash_b64 = stored.split("$", 3)
                salt = base64.b64decode(salt_b64)
                expected = base64.b64decode(hash_b64)
            except (ValueError, Exception):
                return False

            candidate = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode(),
                salt,
                int(iterations)
            )

            return hmac.compare_digest(candidate, expected)

        # Legacy format: bare hex sha256 digest, no salt.
        legacy_candidate = hashlib.sha256(password.encode()).hexdigest()
        return hmac.compare_digest(legacy_candidate, stored)

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
        stored = data.get("master_password", "")

        if not self._verify_hash(password, stored):
            return False

        # Transparent migration: if this vault still has a legacy
        # unsalted-SHA256 hash, upgrade it to salted PBKDF2 now that we
        # have the plaintext password in hand. Runs once, silently.
        if not stored.startswith("pbkdf2_sha256$"):
            data["master_password"] = self._hash(password)
            self._save(data)

        # Unlock and touch on successful verification
        self.unlock()
        return True

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

    # =====================================================
    # PASSWORD STRENGTH
    # =====================================================

    @staticmethod
    def password_strength(password):
        """
        Lightweight, dependency-free strength estimate for UI feedback.
        Returns (score 0-4, label). Not a substitute for a real entropy
        estimator (e.g. zxcvbn) but enough to steer users away from
        obviously weak master passwords at creation time.
        """
        if not password:
            return 0, "Empty"

        score = 0
        if len(password) >= 8:
            score += 1
        if len(password) >= 12:
            score += 1
        if any(c.islower() for c in password) and any(c.isupper() for c in password):
            score += 1
        if any(c.isdigit() for c in password):
            score += 1
        if any(not c.isalnum() for c in password):
            score += 1

        score = min(score, 4)
        labels = ["Very weak", "Weak", "Fair", "Strong", "Very strong"]
        return score, labels[score]