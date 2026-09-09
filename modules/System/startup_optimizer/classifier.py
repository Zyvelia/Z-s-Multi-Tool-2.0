"""
Startup Optimizer — classification.

Looks up startup apps / services against the bundled seed DB
(data/known_items.json), then layers the user's own per-item
overrides on top (some items are legitimately 🟢 for one machine and
🔴 for another — Bluetooth services, VPN clients, etc.).

NOTE: swap _data_dir() below for whatever core/paths.py's actual
AppData helper is called, if it exposes one — this falls back to the
same %APPDATA%\\ZsMultiTool\\ convention used elsewhere in the app so
it works standalone either way.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

Status = Literal["red", "yellow", "green"]

_SEED_PATH = Path(__file__).parent / "data" / "known_items.json"


def _data_dir() -> Path:
    try:
        from core.paths import get_data_dir  # type: ignore
        return Path(get_data_dir("startup_optimizer"))
    except Exception:
        base = Path(os.environ.get("APPDATA", Path.home())) / "ZsMultiTool" / "startup_optimizer"
        base.mkdir(parents=True, exist_ok=True)
        return base


_OVERRIDES_PATH = _data_dir() / "overrides.json"
_BACKUP_LOG_PATH = _data_dir() / "change_log.json"

_UNKNOWN = {"status": "yellow", "description": "Unknown — verify before disabling.",
            "impact": "unknown", "category": "unclassified"}


def _normalize(name: str) -> str:
    n = name.strip().lower()
    for suffix in (".exe", ".lnk", ".dll"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
    return n


class Classifier:
    def __init__(self):
        self._seed = self._load_seed()
        self._overrides = self._load_json(_OVERRIDES_PATH, default={"startup_apps": {}, "services": {}})

    @staticmethod
    def _load_seed() -> dict:
        from .sync import cached_db_path
        cached = cached_db_path(_data_dir())
        if cached is not None:
            try:
                with open(cached, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass  # fall through to bundled seed below
        try:
            with open(_SEED_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"startup_apps": {}, "services": {}, "protected_services": []}

    @staticmethod
    def _load_json(path: Path, default: dict) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def _save_overrides(self) -> None:
        with open(_OVERRIDES_PATH, "w", encoding="utf-8") as f:
            json.dump(self._overrides, f, indent=2)

    def classify(self, name: str, kind: str) -> dict:
        """kind: 'startup_apps' | 'services'"""
        key = _normalize(name)
        override = self._overrides.get(kind, {}).get(key)
        base = self._seed.get(kind, {}).get(key, _UNKNOWN).copy()
        if override:
            base["status"] = override["status"]
            base["user_override"] = True
        base["protected"] = base.get("protected", False) or self.is_protected_service(name)
        return base

    def reload_seed(self) -> None:
        """Call after sync.check_and_update() reports a change."""
        self._seed = self._load_seed()

    def is_protected_service(self, service_name: str) -> bool:
        protected = {p.lower() for p in self._seed.get("protected_services", [])}
        return service_name.lower() in protected

    def set_override(self, name: str, kind: str, status: Status) -> None:
        key = _normalize(name)
        self._overrides.setdefault(kind, {})[key] = {"status": status}
        self._save_overrides()

    def clear_override(self, name: str, kind: str) -> None:
        key = _normalize(name)
        self._overrides.get(kind, {}).pop(key, None)
        self._save_overrides()


# ---------------------------------------------------------------- change log

def log_change(entry: dict) -> None:
    """Append a reversible-change record: {type, name, previous_state,
    new_state, timestamp}. Used for one-click restore."""
    import datetime
    log = Classifier._load_json(_BACKUP_LOG_PATH, default={"entries": []})
    entry = dict(entry)
    entry["timestamp"] = datetime.datetime.now().isoformat(timespec="seconds")
    log["entries"].append(entry)
    log["entries"] = log["entries"][-200:]  # cap the log
    with open(_BACKUP_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)


def load_change_log() -> list[dict]:
    return Classifier._load_json(_BACKUP_LOG_PATH, default={"entries": []})["entries"]
