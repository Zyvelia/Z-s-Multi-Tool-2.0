from __future__ import annotations

import json
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from packaging import version as _version

from core.marketplace import dirs, discover, index as indexmod, package, publisher, versions
from core.updater import APP_VERSION


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_installed() -> dict:
    path = dirs.installed_db_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    modules = data.get("modules")
    if isinstance(modules, dict):
        return modules
    return {}


def save_installed(records: dict):
    dirs.installed_db_path().write_text(
        json.dumps({"modules": records}, indent=2),
        encoding="utf-8",
    )


def app_supports(min_ver: str | None) -> bool:
    if not min_ver:
        return True
    try:
        return _version.parse(APP_VERSION) >= _version.parse(str(min_ver))
    except Exception:
        return True


class MarketplaceClient:
    def __init__(self, settings=None):
        self.settings = settings
        self.last_error = ""

    def catalog_url(self) -> str:
        url = ""
        if self.settings is not None:
            url = str(self.settings.get("marketplace_url") or "").strip()
        return url

    def refresh_index(self) -> dict:
        self.last_error = ""
        publisher.seed_listings_from_bundled()
        local = indexmod.load_json(dirs.publisher_index_path())
        remote_url = self.catalog_url()
        if not remote_url:
            return local
        try:
            remote = indexmod.fetch_index(remote_url)
        except Exception as exc:
            self.last_error = f"Could not reach marketplace URL: {exc}"
            return local
        return indexmod.merge_indexes(local, remote)

    def installed_record(self, module_id: str) -> dict | None:
        return load_installed().get(dirs.slug(module_id))

    def installed_build(self, module_id: str) -> int:
        rec = self.installed_record(module_id)
        if rec:
            return int(rec.get("build") or 0)
        return 0

    def history_builds(self, module_id: str) -> list[int]:
        folder = dirs.history_dir(module_id)
        builds = []
        for path in folder.glob("build-*.zmod"):
            try:
                builds.append(int(path.stem.split("-", 1)[1]))
            except Exception:
                continue
        return sorted(builds)

    def rows(self, plugin_tools: list[dict] | None = None) -> list[dict]:
        index = self.refresh_index()
        installed = load_installed()
        plugins = {dirs.slug(t.get("name") or ""): t for t in (plugin_tools or [])}
        bundled = {t["id"]: t for t in discover.list_bundled_tools()}
        rows = []
        for listing in index.get("modules") or []:
            mid = listing.get("id")
            if not mid:
                continue
            latest = indexmod.latest_release(listing)
            latest_build = int(listing.get("latest_build") or (latest or {}).get("build") or 0)
            rec = installed.get(mid)
            overlay = rec is not None
            plugin = plugins.get(mid)
            source = bundled.get(mid)
            installed_build = int(rec.get("build") or 0) if rec else 0
            if overlay:
                origin = "marketplace"
            elif plugin or source:
                origin = "bundled"
            else:
                origin = "none"
            if latest_build == 0 and origin in ("bundled", "marketplace"):
                status = "included"
            elif origin == "none" and latest_build > 0:
                status = "new"
            elif versions.is_newer(latest_build, installed_build if overlay else 0):
                status = "update"
            elif overlay:
                status = "installed"
            else:
                status = "included"
            rows.append({
                "id": mid,
                "name": listing.get("name") or (plugin or {}).get("name") or mid,
                "category": listing.get("category") or "Utilities",
                "desc": listing.get("desc") or "",
                "icon": listing.get("icon") or "📦",
                "publisher": listing.get("publisher") or "official",
                "latest_build": latest_build,
                "latest_label": (latest or {}).get("label") or (
                    versions.label_for(latest_build) if latest_build else "Included with the app"
                ),
                "installed_build": installed_build if overlay else (0 if origin == "bundled" else None),
                "installed_label": (rec or {}).get("label") or (
                    "Included with the app" if origin == "bundled" else "Not installed"
                ),
                "origin": origin,
                "status": status,
                "can_install": origin == "none" and latest_build > 0,
                "can_update": latest_build > 0 and versions.is_newer(
                    latest_build, installed_build if overlay else 0
                ),
                "can_uninstall": overlay,
                "can_rollback": overlay and any(b < installed_build for b in self.history_builds(mid)),
                "can_publish": source is not None,
                "included": origin == "bundled" and not overlay,
                "min_app_version": listing.get("min_app_version") or (latest or {}).get("min_app_version"),
            })
        rows.sort(key=lambda r: ((r.get("category") or ""), (r.get("name") or "")))
        return rows

    def _resolve_release(self, module_id: str, build: int | None = None) -> tuple[dict, dict, dict]:
        index = self.refresh_index()
        listing = indexmod.listing_by_id(index, module_id)
        if listing is None:
            raise FileNotFoundError(f"No marketplace listing for {module_id}")
        if build is None:
            release = indexmod.latest_release(listing)
        else:
            release = None
            for item in listing.get("releases") or []:
                if int(item.get("build") or 0) == int(build):
                    release = item
                    break
        if release is None:
            raise FileNotFoundError(f"No published package for {module_id}")
        return index, listing, release

    def _download(self, index_url: str, release: dict, dest: Path) -> Path:
        url = indexmod.resolve_package_url(index_url or str(dirs.publisher_index_path()), release)
        if not url:
            raise FileNotFoundError("Listing has no package file.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if url.startswith("http://") or url.startswith("https://"):
            urllib.request.urlretrieve(url, dest)
            return dest
        src = Path(url)
        if src.exists():
            if src.resolve() != dest.resolve():
                shutil.copy2(src, dest)
            return dest
        raise FileNotFoundError(f"Package file not found: {url}")

    def install(self, module_id: str, build: int | None = None, *, allow_downgrade: bool = False) -> dict:
        module_id = dirs.slug(module_id)
        index, listing, release = self._resolve_release(module_id, build)
        candidate = int(release.get("build") or 0)
        current = self.installed_build(module_id)
        rec = self.installed_record(module_id)
        if rec and versions.same_or_older(candidate, current) and not allow_downgrade:
            raise ValueError(
                f"{listing.get('name')} is already on {versions.label_for(current)}. "
                "An older build cannot replace a newer one."
            )
        min_ver = listing.get("min_app_version") or release.get("min_app_version")
        if not app_supports(min_ver):
            raise ValueError(
                f"{listing.get('name')} needs Z's Multi Tool {min_ver} or newer "
                f"(this app is {APP_VERSION})."
            )
        dest = dirs.root() / "downloads" / f"{module_id}-build-{candidate}.zmod"
        index_url = self.catalog_url() or str(dirs.publisher_index_path())
        self._download(index_url, release, dest)
        manifest = package.unpack(dest, dirs.overlay_modules(), expected_sha=release.get("sha256"))
        history = dirs.history_dir(module_id) / f"build-{candidate}.zmod"
        if dest.resolve() != history.resolve():
            shutil.copy2(dest, history)
        records = load_installed()
        records[module_id] = {
            "id": module_id,
            "name": manifest.get("name") or listing.get("name"),
            "build": candidate,
            "label": release.get("label") or versions.label_for(candidate),
            "origin": "marketplace",
            "relpath": manifest.get("relpath"),
            "sha256": release.get("sha256") or package.sha256_file(dest),
            "installed_at": _now(),
            "publisher": listing.get("publisher") or "official",
        }
        save_installed(records)
        return records[module_id]

    def update(self, module_id: str) -> dict:
        return self.install(module_id)

    def update_all(self, plugin_tools: list[dict] | None = None) -> list[dict]:
        results = []
        for row in self.rows(plugin_tools):
            if row.get("can_update"):
                results.append(self.install(row["id"]))
        return results

    def uninstall(self, module_id: str) -> dict:
        module_id = dirs.slug(module_id)
        rec = self.installed_record(module_id)
        if rec is None:
            raise ValueError("This module is included with the app and has no marketplace overlay to remove.")
        rel = (rec.get("relpath") or "").strip("/").replace("\\", "/")
        if rel and ".." not in rel.split("/"):
            target = dirs.overlay_modules().joinpath(*rel.split("/"))
            if target.exists():
                shutil.rmtree(target)
        records = load_installed()
        records.pop(module_id, None)
        save_installed(records)
        return {
            "id": module_id,
            "name": rec.get("name"),
            "relpath": rel,
            "fell_back_to_bundled": any(t["id"] == module_id for t in discover.list_bundled_tools()),
        }

    def rollback(self, module_id: str, build: int | None = None) -> dict:
        module_id = dirs.slug(module_id)
        current = self.installed_build(module_id)
        history = [b for b in self.history_builds(module_id) if b < current]
        if not history:
            raise ValueError("No previous build is saved for rollback.")
        target_build = int(build) if build is not None else history[-1]
        if target_build not in history and target_build >= current:
            raise ValueError("Rollback must target an older saved build.")
        saved = dirs.history_dir(module_id) / f"build-{target_build}.zmod"
        if not saved.exists():
            raise FileNotFoundError(f"Saved build {target_build} is missing.")
        try:
            return self.install(module_id, target_build, allow_downgrade=True)
        except FileNotFoundError:
            manifest = package.unpack(saved, dirs.overlay_modules())
            records = load_installed()
            records[module_id] = {
                "id": module_id,
                "name": manifest.get("name") or module_id,
                "build": target_build,
                "label": versions.label_for(target_build),
                "origin": "marketplace",
                "relpath": manifest.get("relpath"),
                "sha256": package.sha256_file(saved),
                "installed_at": _now(),
                "publisher": "official",
            }
            save_installed(records)
            return records[module_id]

    def publish(self, module_id: str) -> dict:
        return publisher.publish_by_id(module_id)
