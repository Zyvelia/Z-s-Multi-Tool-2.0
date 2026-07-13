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

    def __init__(self, crypto):
        self.crypto = crypto

        if not os.path.exists(self.FILE):
            with open(self.FILE, "w") as f:
                json.dump([], f)

    def _load(self):
        try:
            with open(self.FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []

    def _save(self, data):
        with open(self.FILE, "w") as f:
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

    # ---------------- DELETE ----------------

    def delete_entry(self, entry_id: str):
        data = [item for item in self._load() if item.get("id") != entry_id]
        self._save(data)

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
