# modules/notes/storage.py
#
# Persistent JSON-backed storage for the Notes module.
#
# Each note: {
#   "id": str,          # uuid4 hex, stable identity even if title changes
#   "title": str,
#   "body": str,
#   "links": [{"label": str, "url": str}, ...],
#   "created_at": float,
#   "updated_at": float,
#   "pinned": bool
# }
#
# Data lives at %APPDATA%/ZsMultiTool/notes/data.json. Writes are atomic
# (write to a temp file, then replace) so a crash or forced-close mid-save
# can't corrupt existing notes.

import json
import time
import uuid
from pathlib import Path

from core import paths

DATA_DIR = Path(paths.get_app_data_dir()) / "notes"
DATA_FILE = DATA_DIR / "data.json"

DEFAULT_DATA = {
    "notes": []
}


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
            data = json.load(f)
        if not isinstance(data, dict) or "notes" not in data:
            raise ValueError("data.json missing 'notes'")
    except (json.JSONDecodeError, OSError, ValueError):
        data = _default_data()
        save_data(data)
        return data

    return data


def save_data(data):
    _ensure_dir()
    tmp_path = DATA_FILE.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp_path.replace(DATA_FILE)


def storage_path():
    return str(DATA_FILE)


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

def get_notes():
    """Returns notes sorted pinned-first, then most-recently-updated first."""
    notes = load_data()["notes"]
    return sorted(
        notes,
        key=lambda n: (not n.get("pinned", False), -n.get("updated_at", 0))
    )


def get_note(note_id):
    for n in load_data()["notes"]:
        if n["id"] == note_id:
            return n
    return None


def create_note(title="", body="", links=None):
    data = load_data()
    now = time.time()
    note = {
        "id": uuid.uuid4().hex,
        "title": title.strip() or "Untitled",
        "body": body,
        "links": links or [],
        "created_at": now,
        "updated_at": now,
        "pinned": False
    }
    data["notes"].append(note)
    save_data(data)
    return note


def update_note(note_id, title=None, body=None, links=None):
    data = load_data()
    for n in data["notes"]:
        if n["id"] == note_id:
            if title is not None:
                n["title"] = title.strip() or "Untitled"
            if body is not None:
                n["body"] = body
            if links is not None:
                n["links"] = links
            n["updated_at"] = time.time()
            save_data(data)
            return n
    return None


def delete_note(note_id):
    data = load_data()
    data["notes"] = [n for n in data["notes"] if n["id"] != note_id]
    save_data(data)


def toggle_pin(note_id):
    data = load_data()
    for n in data["notes"]:
        if n["id"] == note_id:
            n["pinned"] = not n.get("pinned", False)
            save_data(data)
            return n
    return None


def search_notes(query):
    query = (query or "").strip().lower()
    if not query:
        return get_notes()

    def matches(n):
        if query in n.get("title", "").lower():
            return True
        if query in n.get("body", "").lower():
            return True
        for link in n.get("links", []):
            if query in link.get("label", "").lower() or query in link.get("url", "").lower():
                return True
        return False

    return [n for n in get_notes() if matches(n)]
