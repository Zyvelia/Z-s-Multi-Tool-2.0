"""Saved SSH hosts and last serial settings. Passwords are never written."""

from __future__ import annotations

import json
from pathlib import Path

from core import paths

_FILE = Path(paths.data_path("ssh_serial", "hosts.json"))

_DEFAULT = {
    "hosts": [],
    "serial": {"port": "", "baud": "115200"},
}


def load() -> dict:
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("hosts", [])
            data.setdefault("serial", _DEFAULT["serial"])
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return json.loads(json.dumps(_DEFAULT))


def save(data: dict) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    _FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def upsert_host(host: dict) -> None:
    data = load()
    name = (host.get("name") or host.get("hostname") or "").strip()
    hosts = [h for h in data["hosts"] if h.get("name") != name]
    hosts.append({
        "name": name,
        "hostname": (host.get("hostname") or "").strip(),
        "port": int(host.get("port") or 22),
        "username": (host.get("username") or "").strip(),
        "key_path": (host.get("key_path") or "").strip(),
    })
    data["hosts"] = sorted(hosts, key=lambda h: h.get("name") or "")
    save(data)


def delete_host(name: str) -> None:
    data = load()
    data["hosts"] = [h for h in data["hosts"] if h.get("name") != name]
    save(data)


def save_serial(port: str, baud: str) -> None:
    data = load()
    data["serial"] = {"port": port, "baud": str(baud)}
    save(data)
