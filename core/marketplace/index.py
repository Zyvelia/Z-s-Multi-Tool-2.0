from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

from core.marketplace import dirs


def empty_index() -> dict:
    return {"name": "Z's Multi Tool Marketplace", "updated": "", "modules": []}


def load_json(path: Path) -> dict:
    if not path.exists():
        return empty_index()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return empty_index()
    data.setdefault("modules", [])
    return data


def save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def fetch_index(url: str) -> dict:
    url = (url or "").strip()
    if not url:
        return empty_index()
    if url.startswith("file://"):
        return load_json(Path(url[7:]))
    path = Path(url)
    if path.exists():
        return load_json(path)
    req = urllib.request.Request(url, headers={"User-Agent": "ZsMultiTool-Marketplace"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    data.setdefault("modules", [])
    return data


def merge_indexes(*indexes: dict) -> dict:
    by_id = {}
    for index in indexes:
        for item in (index or {}).get("modules") or []:
            mid = item.get("id")
            if not mid:
                continue
            prev = by_id.get(mid)
            if prev is None or int(item.get("latest_build") or 0) >= int(prev.get("latest_build") or 0):
                by_id[mid] = item
    return {
        "name": "Z's Multi Tool Marketplace",
        "modules": sorted(by_id.values(), key=lambda m: (m.get("category") or "", m.get("name") or "")),
    }


def listing_by_id(index: dict, module_id: str) -> dict | None:
    module_id = dirs.slug(module_id)
    for item in index.get("modules") or []:
        if item.get("id") == module_id:
            return item
    return None


def latest_release(listing: dict) -> dict | None:
    releases = listing.get("releases") or []
    if not releases:
        return None
    return max(releases, key=lambda r: int(r.get("build") or 0))


def resolve_package_url(index_url: str, release: dict) -> str:
    url = (release.get("url") or "").strip()
    if url:
        return url
    file_rel = (release.get("file") or "").strip()
    if not file_rel:
        return ""
    if Path(file_rel).is_absolute() and Path(file_rel).exists():
        return file_rel
    base = (index_url or "").strip()
    if base.startswith("http://") or base.startswith("https://"):
        if not base.endswith("/") and "/" in base:
            base = base.rsplit("/", 1)[0] + "/"
        return urljoin(base, file_rel)
    index_path = Path(base) if base else dirs.publisher_index_path()
    if str(index_path).endswith(".json"):
        return str(index_path.parent / file_rel)
    return str(Path(base) / file_rel)
