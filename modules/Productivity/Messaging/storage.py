# modules/Productivity/Messaging/storage.py
#
# Persistent JSON-backed storage for the Messaging module. Modeled on
# modules/Productivity/Notes/storage.py.
#
# Each message: {
#   "id": str,          # uuid4 hex
#   "sender_id": str,   # whichever device/person sent it
#   "text": str,
#   "sent_at": float,   # epoch seconds
# }
#
# Data lives at %APPDATA%/ZsMultiTool/messages/data.json. Writes are
# atomic (temp file + replace) so a crash mid-save can't corrupt history.

import json
import time
import uuid
from pathlib import Path

from core import paths

DATA_DIR = Path(paths.get_app_data_dir()) / "messages"
DATA_FILE = DATA_DIR / "data.json"

DEFAULT_DATA = {"messages": []}


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _default_data():
    return json.loads(json.dumps(DEFAULT_DATA))


def load_data():
    _ensure_dir()
    if not DATA_FILE.exists():
        data = _default_data()
        save_data(data)
        return data
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return _default_data()


def save_data(data):
    _ensure_dir()
    tmp = DATA_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp.replace(DATA_FILE)


def append_message(sender_id: str, text: str, message_id: str = None) -> dict:
    data = load_data()
    message = {
        "id": message_id or uuid.uuid4().hex,
        "sender_id": sender_id,
        "text": text,
        "sent_at": time.time(),
    }
    data["messages"].append(message)
    save_data(data)
    return message


def get_messages_since(since: float = 0.0) -> list:
    data = load_data()
    return [m for m in data["messages"] if m["sent_at"] > since]
