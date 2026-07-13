# core/services/totp_service.py
#
# Authenticator (2FA) codes, same idea as Google/Microsoft Authenticator —
# implements the standard TOTP algorithm (RFC 6238) that every "scan this
# QR code or enter this key manually" 2FA setup (Discord included) is
# built on. No proprietary anything: any TOTP-compliant secret works here,
# and any TOTP-compliant app can read secrets generated here.
#
# Secrets are stored the same way vault passwords are — encrypted at rest
# via the shared CryptoService, in their own file so a TOTP secret leak
# and a password leak are two separate incidents, not one.

import base64
import hashlib
import hmac
import json
import os
import struct
import time
import uuid
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlparse

from core import paths

DEFAULT_DIGITS = 6
DEFAULT_PERIOD = 30


# =====================================================
# PURE TOTP ALGORITHM (RFC 6238 / RFC 4226)
# =====================================================
# No file/network access below this line — easy to reason about and
# reuse (e.g. a future CLI or test) independent of storage.

def normalize_secret(secret: str) -> str:
    """Base32 secrets are case-insensitive and often shown with spaces
    for readability (e.g. 'ABCD EFGH IJKL') — strip that before use."""
    return secret.strip().replace(" ", "").upper()


def _decode_secret(secret: str) -> bytes:
    s = normalize_secret(secret)
    s += "=" * ((-len(s)) % 8)  # base32 needs padding to a multiple of 8
    return base64.b32decode(s)


def is_valid_secret(secret: str) -> bool:
    try:
        decoded = _decode_secret(secret)
        return len(decoded) > 0
    except Exception:
        return False


def _hotp(secret_bytes: bytes, counter: int, digits: int) -> str:
    msg = struct.pack(">Q", counter)
    digest = hmac.new(secret_bytes, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code_int % (10 ** digits)).zfill(digits)


def generate_code(secret: str, digits: int = DEFAULT_DIGITS, period: int = DEFAULT_PERIOD, at: float = None) -> str:
    at = time.time() if at is None else at
    counter = int(at // period)
    return _hotp(_decode_secret(secret), counter, digits)


def seconds_remaining(period: int = DEFAULT_PERIOD, at: float = None) -> int:
    at = time.time() if at is None else at
    return period - int(at % period)


def parse_otpauth_uri(text: str):
    """
    Accepts a full 'otpauth://totp/...' URI (some services offer this as
    a copyable alternative to the QR code) and pulls out the secret plus
    a reasonable name/issuer. Returns None if `text` isn't one — callers
    should fall back to treating it as a raw secret instead.
    """
    try:
        text = text.strip()
        if not text.lower().startswith("otpauth://"):
            return None

        parsed = urlparse(text)
        qs = parse_qs(parsed.query)

        secret = qs.get("secret", [""])[0]
        if not secret:
            return None

        issuer = qs.get("issuer", [""])[0]
        label = unquote(parsed.path.lstrip("/"))

        if ":" in label:
            label_issuer, _, label = label.partition(":")
            issuer = issuer or label_issuer

        return {
            "name": label.strip() or issuer or "Account",
            "issuer": issuer.strip(),
            "secret": secret,
        }
    except Exception:
        return None


# =====================================================
# STORAGE
# =====================================================

class TotpService:

    FILE = paths.data_path("totp.json")

    # Deleted entries land here instead of disappearing outright — a
    # misclick on the remove button (or removing the wrong account) would
    # otherwise mean re-doing 2FA setup with the site itself, which isn't
    # always possible without the original device. Trash is capped by age
    # rather than count, same idea as a recycle bin.
    TRASH_FILE = paths.data_path("totp_trash.json")
    TRASH_RETENTION_DAYS = 30

    def __init__(self, crypto):
        self.crypto = crypto

        if not os.path.exists(self.FILE):
            with open(self.FILE, "w") as f:
                json.dump([], f)

        if not os.path.exists(self.TRASH_FILE):
            with open(self.TRASH_FILE, "w") as f:
                json.dump([], f)

        self._purge_expired_trash()

    def _load(self):
        try:
            with open(self.FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []

    def _save(self, data):
        with open(self.FILE, "w") as f:
            json.dump(data, f, indent=4)

    def _load_trash(self):
        try:
            with open(self.TRASH_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []

    def _save_trash(self, data):
        with open(self.TRASH_FILE, "w") as f:
            json.dump(data, f, indent=4)

    # ---------------- CREATE ----------------

    def add_entry(self, name: str, secret: str, issuer: str = ""):
        secret = normalize_secret(secret)

        if not is_valid_secret(secret):
            raise ValueError("That doesn't look like a valid authenticator secret.")

        data = self._load()
        data.append({
            "id": str(uuid.uuid4()),
            "name": name.strip() or "Account",
            "issuer": issuer.strip(),
            "secret": self.crypto.encrypt(secret),
            "created": datetime.now().isoformat(),
        })
        self._save(data)

    # ---------------- DELETE / RECOVER ----------------

    def delete_entry(self, entry_id: str):
        """Soft delete: moves the entry to trash rather than erasing it,
        so an accidental click (or the wrong row) can be undone. Use
        purge_entry() for a permanent, unrecoverable delete."""
        data = self._load()
        keep, removed = [], None
        for item in data:
            if item.get("id") == entry_id:
                removed = item
            else:
                keep.append(item)

        if removed is None:
            return

        self._save(keep)

        trash = self._load_trash()
        removed["deleted"] = datetime.now().isoformat()
        trash.append(removed)
        self._save_trash(trash)

    def get_trash(self):
        """Deleted entries still awaiting purge, decrypted for display —
        same trust boundary as get_entries() (vault must be unlocked)."""
        results = []
        for item in self._load_trash():
            try:
                results.append({
                    "id": item.get("id"),
                    "name": item.get("name", "Account"),
                    "issuer": item.get("issuer", ""),
                    "secret": self.crypto.decrypt(item["secret"]),
                    "created": item.get("created", ""),
                    "deleted": item.get("deleted", ""),
                })
            except Exception:
                pass

        results.sort(key=lambda e: e["deleted"], reverse=True)
        return results

    def restore_entry(self, entry_id: str):
        """Moves an entry back out of trash and into the live list."""
        trash = self._load_trash()
        keep, restored = [], None
        for item in trash:
            if item.get("id") == entry_id:
                restored = item
            else:
                keep.append(item)

        if restored is None:
            return False

        self._save_trash(keep)

        restored.pop("deleted", None)
        data = self._load()
        data.append(restored)
        self._save(data)
        return True

    def purge_entry(self, entry_id: str):
        """Permanently, irreversibly deletes a trashed entry."""
        trash = [item for item in self._load_trash() if item.get("id") != entry_id]
        self._save_trash(trash)

    def _purge_expired_trash(self):
        """Drops trash entries older than TRASH_RETENTION_DAYS. Called on
        startup so trash doesn't grow forever, without needing a background
        timer — cheap because it only runs once per app launch."""
        trash = self._load_trash()
        if not trash:
            return

        cutoff = datetime.now().timestamp() - (self.TRASH_RETENTION_DAYS * 86400)
        kept = []
        for item in trash:
            try:
                deleted_at = datetime.fromisoformat(item.get("deleted", "")).timestamp()
                if deleted_at >= cutoff:
                    kept.append(item)
            except Exception:
                kept.append(item)  # malformed timestamp — don't lose data over it

        if len(kept) != len(trash):
            self._save_trash(kept)

    # ---------------- RENAME ----------------

    def rename_entry(self, entry_id: str, name: str, issuer: str = ""):
        data = self._load()
        for item in data:
            if item.get("id") == entry_id:
                item["name"] = name.strip() or "Account"
                item["issuer"] = issuer.strip()
                break
        self._save(data)

    # ---------------- READ ----------------

    def get_entries(self):
        """Returns entries with decrypted secrets — only call this once
        the vault is already unlocked (same trust boundary as VaultService)."""
        results = []
        for item in self._load():
            try:
                results.append({
                    "id": item.get("id"),
                    "name": item.get("name", "Account"),
                    "issuer": item.get("issuer", ""),
                    "secret": self.crypto.decrypt(item["secret"]),
                    "created": item.get("created", ""),
                })
            except Exception:
                pass

        results.sort(key=lambda e: e["name"].lower())
        return results

    def count(self):
        return len(self._load())
