# modules/notification_mirror/storage.py
#
# Settings + (optional, opt-in) history for Z Connect Notifications.
# Same atomic JSON read/write convention as quick_send/storage.py and
# notes/storage.py. Notification bodies are only ever written to disk
# if the user explicitly turns history on (see DEFAULTS["history_enabled"]
# below) — per-conversation content stays in memory only otherwise.

import json
import os
import time

from core import paths

CONFIG_FILE = paths.data_path("notification_mirror", "settings.json")
HISTORY_FILE = paths.data_path("notification_mirror", "history.json")

# Kept intentionally small — this is a rolling buffer, not an archive.
# Matches the "Ability to clear mirrored notification history" requirement
# without letting the file grow unbounded.
MAX_HISTORY_ITEMS = 300

DEFAULTS = {
    "enabled": False,  # global mirroring on/off — separate from Go Live
    # Per-app mirroring toggles. Populated/extended dynamically as new
    # notifying apps are observed (see add_known_app below); these five
    # are just sensible pre-checked seeds matching the mockup.
    "apps": {
        "Discord": True,
        "Steam": True,
        "Google Chrome": True,
        "Microsoft Outlook": True,
        "Spotify": False,
        "Windows": True,
    },
    "privacy_mode": "hide_sensitive",  # "full" | "hide_sensitive" | "app_only"
    "real_time": True,
    "sync_dismissal": True,
    "forward_actions": True,
    "queue_while_offline": True,
    "only_when_unlocked": False,
    "history_enabled": False,
    "sensitive_apps": [  # always privacy-clamped regardless of privacy_mode
        "Microsoft Authenticator", "Google Authenticator", "Steam",
    ],
}


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)  # atomic on both Windows and POSIX
    except Exception as e:
        print(f"[notification_mirror] Failed saving {path}: {e}")


def get_settings():
    saved = _load_json(CONFIG_FILE, {})
    merged = dict(DEFAULTS)
    merged.update(saved)
    # Deep-merge the apps dict specifically, so a saved settings.json from
    # before a new default app existed doesn't lose that new app's default.
    merged["apps"] = {**DEFAULTS["apps"], **saved.get("apps", {})}
    return merged


def save_settings(settings: dict):
    _save_json(CONFIG_FILE, settings)


def set_app_enabled(app_name: str, enabled: bool):
    settings = get_settings()
    settings["apps"][app_name] = enabled
    save_settings(settings)


def add_known_app(app_name: str):
    """
    Called by listener.py the first time a given app produces a
    notification, so the Settings page's app list can be "dynamically
    generated from applications that actually produce notifications"
    per spec, instead of a fixed hardcoded list. Defaults new apps to
    mirroring ON — the user can uncheck ones they don't want.
    """
    settings = get_settings()
    if app_name not in settings["apps"]:
        settings["apps"][app_name] = True
        save_settings(settings)


def is_app_enabled(app_name: str) -> bool:
    settings = get_settings()
    return settings["apps"].get(app_name, True)


# ---------------------------------------------------------------------
# History — only ever written to if history_enabled is True. Cleared
# entirely on privacy_mode change to "app_only" isn't automatic (that
# would be surprising); the user clears it explicitly via /api/history
# DELETE or the app-only cases just stop *adding* bodies going forward.
# ---------------------------------------------------------------------

def append_history(entry: dict):
    if not get_settings().get("history_enabled"):
        return
    items = _load_json(HISTORY_FILE, [])
    items.append(entry)
    if len(items) > MAX_HISTORY_ITEMS:
        items = items[-MAX_HISTORY_ITEMS:]
    _save_json(HISTORY_FILE, items)


def get_history():
    return _load_json(HISTORY_FILE, [])


def clear_history():
    _save_json(HISTORY_FILE, [])
