from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from core.marketplace import dirs, discover, index as indexmod, package, versions


def _state() -> dict:
    path = dirs.publisher_state_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"builds": {}}
    return {"builds": {}}


def _save_state(state: dict):
    dirs.publisher_state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")


def current_build(module_id: str) -> int:
    return int((_state().get("builds") or {}).get(dirs.slug(module_id)) or 0)


def publish_tool(tool: dict, publisher: str = "official") -> dict:
    module_id = dirs.slug(tool["id"])
    state = _state()
    builds = state.setdefault("builds", {})
    build = versions.next_build(builds.get(module_id))
    dest = dirs.publisher_root() / "packages" / module_id / f"build-{build}.zmod"
    meta = dict(tool.get("meta") or {})
    meta["publisher"] = publisher
    manifest = package.pack(module_id, meta, tool["root"], tool["relpath"], dest, build)
    builds[module_id] = build
    _save_state(state)

    listing = {
        "id": module_id,
        "name": manifest["name"],
        "category": manifest["category"],
        "desc": manifest["desc"],
        "icon": manifest["icon"],
        "publisher": publisher,
        "latest_build": build,
        "min_app_version": manifest.get("min_app_version") or "4.0.5",
        "releases": [],
    }
    data = indexmod.load_json(dirs.publisher_index_path())
    existing = indexmod.listing_by_id(data, module_id)
    if existing:
        listing["releases"] = list(existing.get("releases") or [])
        data["modules"] = [m for m in data["modules"] if m.get("id") != module_id]
    listing["releases"].append({
        "build": build,
        "label": manifest["label"],
        "published_at": manifest["published_at"],
        "sha256": manifest["sha256"],
        "file": f"packages/{module_id}/build-{build}.zmod",
    })
    listing["releases"] = sorted(listing["releases"], key=lambda r: int(r["build"]))[-20:]
    listing["latest_build"] = max(int(r["build"]) for r in listing["releases"])
    data["modules"].append(listing)
    data["updated"] = datetime.now(timezone.utc).isoformat()
    indexmod.save_json(dirs.publisher_index_path(), data)
    return {"manifest": manifest, "package": str(dest), "listing": listing}


def publish_by_id(module_id: str, publisher: str = "official") -> dict:
    module_id = dirs.slug(module_id)
    for tool in discover.list_bundled_tools():
        if tool["id"] == module_id:
            return publish_tool(tool, publisher=publisher)
    raise FileNotFoundError(f"No bundled tool matching {module_id}")


def seed_listings_from_bundled():
    """List bundled tools in the local index so they show in the Market before a first publish."""
    data = indexmod.load_json(dirs.publisher_index_path())
    have = {m.get("id") for m in data.get("modules") or []}
    changed = False
    for tool in discover.list_bundled_tools():
        if tool["id"] in have:
            continue
        meta = tool["meta"]
        data.setdefault("modules", []).append({
            "id": tool["id"],
            "name": meta.get("name"),
            "category": meta.get("category") or "Utilities",
            "desc": meta.get("desc") or "",
            "icon": meta.get("icon") or "📦",
            "publisher": "official",
            "latest_build": 0,
            "included_with_app": True,
            "releases": [],
        })
        have.add(tool["id"])
        changed = True
    if changed:
        data["updated"] = datetime.now(timezone.utc).isoformat()
        indexmod.save_json(dirs.publisher_index_path(), data)
    return data


def copy_index_for_hosting(dest_dir: str | Path):
    """Copy publisher index + packages so you can upload the folder as-is."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    src = dirs.publisher_root()
    if dirs.publisher_index_path().exists():
        shutil.copy2(dirs.publisher_index_path(), dest / "index.json")
    packages = src / "packages"
    if packages.exists():
        shutil.copytree(packages, dest / "packages", dirs_exist_ok=True)
    return dest
