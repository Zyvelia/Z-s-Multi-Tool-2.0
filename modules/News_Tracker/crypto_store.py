"""
crypto_store.py
Encrypted-at-rest storage for user-supplied API keys.

Why encryption and not hashing: these keys have to be sent back out to
third-party APIs (Fortnite-API, Steam, etc.) to authenticate requests.
Hashing is one-way — a hashed key can never be turned back into the real
key, so a hashed Fortnite key would just stop working. What actually
keeps a key safe at rest while still usable is symmetric encryption:
unreadable if someone opens the JSON file directly, but decryptable in
memory the moment a request needs to go out.

This uses `cryptography`'s Fernet (AES-128-CBC + HMAC). Two files live
in the plugin's data dir:
    .enc_keyfile   - the local encryption key itself (generated once on
                     first use; this file is what actually needs to stay
                     secret — treat it like a password)
    api_keys.json  - {key_id: {provider, label, token (encrypted),
                                extra (unencrypted config), added_at}}

`extra` holds non-secret per-entry config for the "custom" provider
(base URL, header name, etc.) — nothing sensitive, so it's stored
alongside the entry rather than inside the encrypted token.
"""

import json
import os
import time
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from core import paths

DATA_DIR = Path(paths.get_app_data_dir()) / "news_tracker"
KEYFILE = DATA_DIR / ".enc_keyfile"
KEYS_FILE = DATA_DIR / "api_keys.json"


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_fernet():
    _ensure_dir()
    if not KEYFILE.exists():
        key = Fernet.generate_key()
        with open(KEYFILE, "wb") as f:
            f.write(key)
        try:
            os.chmod(KEYFILE, 0o600)  # best-effort; no-op on Windows
        except OSError:
            pass
    else:
        key = KEYFILE.read_bytes()
    return Fernet(key)


def _load_keys():
    _ensure_dir()
    if not KEYS_FILE.exists():
        return {}
    try:
        with open(KEYS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_keys(keys):
    _ensure_dir()
    tmp_path = KEYS_FILE.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(keys, f, indent=2)
    tmp_path.replace(KEYS_FILE)


def _mask(raw_value):
    if len(raw_value) <= 4:
        return "•" * len(raw_value)
    return ("•" * (len(raw_value) - 4)) + raw_value[-4:]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_keys():
    """Metadata + masked preview only — never the raw or encrypted token.
    Safe to hand straight to the UI."""
    keys = _load_keys()
    if not keys:
        return []
    fernet = _load_fernet()
    out = []
    for key_id, entry in keys.items():
        try:
            raw = fernet.decrypt(entry["token"].encode()).decode()
            preview = _mask(raw)
        except (InvalidToken, KeyError, ValueError):
            preview = "•• (unreadable — re-add this key)"
        out.append({
            "id": key_id,
            "provider": entry.get("provider", "custom"),
            "label": entry.get("label", ""),
            "preview": preview,
            "extra": entry.get("extra", {}),
            "added_at": entry.get("added_at", 0),
        })
    out.sort(key=lambda e: e["added_at"])
    return out


def add_key(provider, label, raw_value, extra=None):
    """Encrypt and store a new key. Returns the new entry's id."""
    raw_value = (raw_value or "").strip()
    if not raw_value:
        raise ValueError("API key value can't be empty.")
    if not provider:
        raise ValueError("Choose a provider for this key.")

    fernet = _load_fernet()
    token = fernet.encrypt(raw_value.encode()).decode()

    keys = _load_keys()
    key_id = uuid.uuid4().hex[:12]
    keys[key_id] = {
        "provider": provider,
        "label": (label or "").strip() or provider,
        "token": token,
        "extra": extra or {},
        "added_at": time.time(),
    }
    _save_keys(keys)
    return key_id


def remove_key(key_id):
    keys = _load_keys()
    keys.pop(key_id, None)
    _save_keys(keys)


def get_raw_value(key_id):
    """Decrypt one key by id. Returns None if missing or undecryptable."""
    keys = _load_keys()
    entry = keys.get(key_id)
    if not entry:
        return None
    fernet = _load_fernet()
    try:
        return fernet.decrypt(entry["token"].encode()).decode()
    except (InvalidToken, KeyError, ValueError):
        return None


def get_keys_for_provider(provider):
    """id/label pairs for every stored key under a given provider — lets a
    user store more than one key per provider (e.g. two Fortnite accounts)."""
    keys = _load_keys()
    return [
        {"id": kid, "label": e.get("label") or provider}
        for kid, e in keys.items()
        if e.get("provider") == provider
    ]


def get_entry(key_id):
    """Full entry (decrypted token + extra config) for actually making a
    request — used by game_providers.py, not the UI."""
    keys = _load_keys()
    entry = keys.get(key_id)
    if not entry:
        return None
    return {
        "provider": entry.get("provider"),
        "label": entry.get("label"),
        "token": get_raw_value(key_id),
        "extra": entry.get("extra", {}),
    }


def storage_path():
    return str(KEYS_FILE)
