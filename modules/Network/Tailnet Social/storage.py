from __future__ import annotations

import json
import secrets
import time
from pathlib import Path

from core import paths

_FILE = Path(paths.data_path("tailnet_social", "state.json"))


def _empty() -> dict:
    return {"invites": [], "queue": []}


def load() -> dict:
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("invites", [])
            data.setdefault("queue", [])
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return _empty()


def save(data: dict) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    _FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def issue_invite(label: str, *, console: bool = False) -> dict:
    data = load()
    invite = {
        "key": secrets.token_urlsafe(18),
        "label": (label or "friend").strip() or "friend",
        "console": bool(console),
        "created": time.time(),
    }
    data["invites"].append(invite)
    save(data)
    return invite


def revoke_invite(key: str) -> None:
    data = load()
    data["invites"] = [i for i in data["invites"] if i.get("key") != key]
    save(data)


def check_invite(key: str) -> dict | None:
    key = (key or "").strip()
    if not key:
        return None
    for invite in load().get("invites", []):
        if invite.get("key") == key:
            return invite
    return None


def queue_add(title: str, by: str = "") -> dict:
    data = load()
    item = {"title": title.strip(), "by": by, "ts": time.time()}
    data["queue"].append(item)
    save(data)
    return item


def queue_list() -> list:
    return load().get("queue", [])


def queue_clear() -> None:
    data = load()
    data["queue"] = []
    save(data)
