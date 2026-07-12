"""
storage.py
Persistent JSON-backed storage for the Weather & News Tracker plugin.

Everything the user configures survives a restart:
    - custom_feeds:    user-defined keyword/topic feeds, e.g. {"name": "AI", "query": "artificial intelligence"}
    - saved_articles:  headlines the user has explicitly "kept" / bookmarked
    - settings:        preferences (units, refresh interval, page size, etc.)

Data lives at %APPDATA%/ZsMultiTool/news_tracker/data.json (older versions
stored it at ~/.weather_news_tracker/data.json — that gets migrated in
automatically the first time this runs). Writes are atomic (write to
a temp file, then replace) to avoid corrupting the file if the app is closed
mid-write.
"""

import json
import os
import time
from pathlib import Path

from core import paths

DATA_DIR = Path(paths.get_app_data_dir()) / "news_tracker"
DATA_FILE = Path(paths.migrate_legacy_path(
    str(DATA_DIR / "data.json"),
    os.path.join(os.path.expanduser("~"), ".weather_news_tracker", "data.json")
))

DEFAULT_DATA = {
    "custom_feeds": [],
    "saved_articles": [],
    "settings": {
        "country": "us",
        "page_size": 15,
        "refresh_interval_minutes": 0,   # 0 = manual refresh only
        "temp_unit": "C",                # "C" or "F"
    },
}


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _default_data():
    return json.loads(json.dumps(DEFAULT_DATA))


def load_data():
    """Load all persisted data, creating the file with defaults if needed."""
    _ensure_dir()
    if not DATA_FILE.exists():
        data = _default_data()
        save_data(data)
        return data

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("data.json did not contain an object")
    except (json.JSONDecodeError, OSError, ValueError):
        data = _default_data()
        save_data(data)
        return data

    # Forward-compatible merge: fill in any keys that didn't exist yet
    # (e.g. the file was written by an older version of the plugin).
    changed = False
    for key, val in DEFAULT_DATA.items():
        if key not in data:
            data[key] = val
            changed = True
    settings = data.setdefault("settings", {})
    for key, val in DEFAULT_DATA["settings"].items():
        if key not in settings:
            settings[key] = val
            changed = True
    if changed:
        save_data(data)
    return data


def save_data(data):
    """Atomically write the full data dict to disk."""
    _ensure_dir()
    tmp_path = DATA_FILE.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp_path.replace(DATA_FILE)


def storage_path():
    """Return the on-disk path where data is stored (shown in Settings)."""
    return str(DATA_FILE)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_settings():
    return load_data()["settings"]


def update_setting(key, value):
    data = load_data()
    data["settings"][key] = value
    save_data(data)
    return data["settings"]


# ---------------------------------------------------------------------------
# Custom feeds ("news topics people want to keep tracking")
# ---------------------------------------------------------------------------

def get_custom_feeds():
    return load_data()["custom_feeds"]


def add_custom_feed(name, query):
    """Add a new custom feed, or update the query if the name already exists."""
    data = load_data()
    name = (name or "").strip()
    query = (query or "").strip()
    if not name or not query:
        return data["custom_feeds"]

    for feed in data["custom_feeds"]:
        if feed["name"].lower() == name.lower():
            feed["query"] = query
            save_data(data)
            return data["custom_feeds"]

    data["custom_feeds"].append({"name": name, "query": query})
    save_data(data)
    return data["custom_feeds"]


def remove_custom_feed(name):
    data = load_data()
    data["custom_feeds"] = [f for f in data["custom_feeds"] if f["name"] != name]
    save_data(data)
    return data["custom_feeds"]


# ---------------------------------------------------------------------------
# Saved / "kept" articles
# ---------------------------------------------------------------------------

def get_saved_articles():
    return load_data()["saved_articles"]


def is_article_saved(url):
    if not url:
        return False
    return any(a.get("url") == url for a in get_saved_articles())


def save_article(article):
    """Bookmark a headline dict ({"title", "source", "url"}) for later."""
    data = load_data()
    url = article.get("url") or ""

    if url and any(a.get("url") == url for a in data["saved_articles"]):
        return data["saved_articles"]  # already kept

    entry = {
        "title": article.get("title", "(untitled)"),
        "source": article.get("source", "Unknown"),
        "url": url,
        "saved_at": time.time(),
    }
    data["saved_articles"].insert(0, entry)
    save_data(data)
    return data["saved_articles"]


def remove_saved_article(url):
    data = load_data()
    data["saved_articles"] = [a for a in data["saved_articles"] if a.get("url") != url]
    save_data(data)
    return data["saved_articles"]


def clear_saved_articles():
    data = load_data()
    data["saved_articles"] = []
    save_data(data)


def clear_all_data():
    save_data(_default_data())
