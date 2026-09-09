"""
Startup Optimizer — classification DB auto-update.

Hosts on Cloudflare Pages (free static hosting): a tiny manifest.json
with a version number, and the full known_items.json next to it. On
rescan (or app launch), we check the manifest; if its version is
newer than what we've cached, we pull the full file and cache it
locally. Bundled data/known_items.json is always the offline fallback
— nothing here can leave the app without a working classification DB.

Fill in CLOUD_BASE_URL after deploying the Pages project.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

CLOUD_BASE_URL = "https://zsmultitool-db.itszyvelia.workers.dev"
_TIMEOUT = 4  # seconds — never let a slow/dead network stall the UI thread caller


def _get_json(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def check_and_update(cache_dir: Path) -> tuple[bool, str]:
    """Runs on a background thread (network I/O). Returns (updated, message).
    Safe to call often — no-ops instantly if the manifest is unreachable
    or already current."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = cache_dir / "manifest.json"
    db_path = cache_dir / "known_items.json"

    remote_manifest = _get_json(f"{CLOUD_BASE_URL}/manifest.json")
    if remote_manifest is None:
        return False, "Couldn't reach the update server (offline, or not deployed yet)."

    local_version = 0
    if manifest_path.exists():
        try:
            local_version = json.loads(manifest_path.read_text(encoding="utf-8")).get("version", 0)
        except Exception:
            local_version = 0

    remote_version = remote_manifest.get("version", 0)
    if remote_version <= local_version:
        return False, f"Classification database is up to date (v{local_version})."

    remote_db = _get_json(f"{CLOUD_BASE_URL}/known_items.json")
    if remote_db is None:
        return False, "Manifest updated but the database fetch failed — will retry next scan."

    db_path.write_text(json.dumps(remote_db, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(remote_manifest, indent=2), encoding="utf-8")
    return True, f"Classification database updated to v{remote_version}."


def cached_db_path(cache_dir: Path) -> Path | None:
    path = cache_dir / "known_items.json"
    return path if path.exists() else None
