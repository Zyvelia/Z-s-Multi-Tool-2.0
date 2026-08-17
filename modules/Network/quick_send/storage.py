# modules/quick_send/storage.py
#
# Config + a small log of received files for the Quick Send module.
# Follows the same paths.data_path() convention every other module uses
# for its own settings (see core/paths.py).

import json
import os
import time

from core import paths

CONFIG_FILE = paths.data_path("quick_send", "config.json")
LOG_FILE = paths.data_path("quick_send", "received_log.json")

_DEFAULT_INBOX = os.path.join(os.path.expanduser("~"), "Downloads", "Quick Send Inbox")
_DEFAULT_OUTBOX = os.path.join(os.path.expanduser("~"), "Desktop", "Quick Send Shared")


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
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[quick_send] Failed saving {path}: {e}")


def get_config():
    cfg = _load_json(CONFIG_FILE, {})
    inbox = cfg.get("inbox_dir") or _DEFAULT_INBOX
    outbox = cfg.get("outbox_dir") or _DEFAULT_OUTBOX
    os.makedirs(inbox, exist_ok=True)
    os.makedirs(outbox, exist_ok=True)
    return {"inbox_dir": inbox, "outbox_dir": outbox}


def set_inbox_dir(path):
    cfg = _load_json(CONFIG_FILE, {})
    cfg["inbox_dir"] = path
    _save_json(CONFIG_FILE, cfg)


def set_outbox_dir(path):
    cfg = _load_json(CONFIG_FILE, {})
    cfg["outbox_dir"] = path
    _save_json(CONFIG_FILE, cfg)


def log_received(filename, size, sender_note=""):
    """Appends to the "recently received" list shown in the desktop tab.
    Keeps the most recent 200 entries."""
    entries = _load_json(LOG_FILE, [])
    entries.insert(0, {
        "filename": filename,
        "size": size,
        "received_at": time.time(),
        "note": sender_note,
    })
    entries = entries[:200]
    _save_json(LOG_FILE, entries)
    return entries


def get_received_log():
    return _load_json(LOG_FILE, [])


def unique_path(directory, filename):
    """If filename already exists in directory, appends ' (2)', ' (3)',
    etc. before the extension — never silently overwrites an existing
    file that happens to share a name."""
    base, ext = os.path.splitext(filename)
    candidate = filename
    n = 2
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{base} ({n}){ext}"
        n += 1
    return os.path.join(directory, candidate)


def list_outbox_files():
    cfg = get_config()
    outbox = cfg["outbox_dir"]
    files = []
    try:
        for name in os.listdir(outbox):
            full = os.path.join(outbox, name)
            if os.path.isfile(full):
                stat = os.stat(full)
                files.append({
                    "name": name,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                })
    except Exception as e:
        print(f"[quick_send] Failed listing outbox: {e}")
    files.sort(key=lambda f: f["modified"], reverse=True)
    return files
