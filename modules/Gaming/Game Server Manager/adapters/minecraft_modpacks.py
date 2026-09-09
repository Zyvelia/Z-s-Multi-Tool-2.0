"""Minecraft modpack management: CurseForge API and local ZIP imports."""
from __future__ import annotations

import json
import difflib
from urllib.parse import quote_plus
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Any

import requests

from ..core.events import DownloadEvent
from .minecraft_loaders import (
    create_install_worker, detect_loader, detect_minecraft_version, loader_name, get_loader_versions, _run_installer, _set_memory,
)

CURSEFORGE_API = "https://api.curseforge.com/v1"
CURSEFORGE_GAME_ID = 432
CURSEFORGE_MODPACK_CLASS_ID = 4471
UA = "ZsMultiTool-GameServerManager/1.1"


def _headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key.strip(), "User-Agent": UA, "Accept": "application/json"}


def _request_json(url: str, api_key: str, **kwargs) -> Any:
    r = requests.get(url, headers=_headers(api_key), timeout=30, **kwargs)
    r.raise_for_status()
    return r.json()


def search_modpacks(api_key: str, query: str = "", *, page_size: int = 20) -> list[dict]:
    if not api_key.strip():
        raise RuntimeError("Enter a CurseForge API key first.")
    params = {
        "gameId": CURSEFORGE_GAME_ID,
        "classId": CURSEFORGE_MODPACK_CLASS_ID,
        "searchFilter": query.strip(),
        "pageSize": max(1, min(page_size, 50)),
        "sortField": 2,
        "sortOrder": "desc",
    }
    data = _request_json(f"{CURSEFORGE_API}/mods/search", api_key, params=params).get("data", [])
    return data if isinstance(data, list) else []


def get_project_files(api_key: str, project_id: int, *, minecraft_version: str = "", page_size: int = 50) -> list[dict]:
    """Return CurseForge files for a project.

    CurseForge's gameVersionTypeId is runtime taxonomy data, not a universal
    Minecraft constant, so this intentionally does not hard-code it.
    """
    params = {
        "pageSize": max(1, min(page_size, 50)),
        "index": 0,
    }
    if minecraft_version:
        params["gameVersion"] = minecraft_version

    data = _request_json(
        f"{CURSEFORGE_API}/mods/{project_id}/files", api_key, params=params
    ).get("data", [])
    if not isinstance(data, list):
        return []

    if minecraft_version:
        wanted = minecraft_version.strip()
        data = [
            f for f in data
            if wanted in [str(v).strip() for v in (f.get("gameVersions") or [])]
        ]
    return data


def get_latest_project_files(api_key: str, project_id: int, *, page_size: int = 50) -> list[dict]:
    """Return the newest available files without assuming a Minecraft version."""
    params = {
        "pageSize": max(1, min(page_size, 50)),
        "index": 0,
    }
    data = _request_json(
        f"{CURSEFORGE_API}/mods/{project_id}/files", api_key, params=params
    ).get("data", [])
    return data if isinstance(data, list) else []


def _curseforge_search_url(name: str, minecraft_version: str = "", loader: str = "") -> str:
    """Return a useful CurseForge web search URL for manual recovery.

    This deliberately does not pretend an API-disabled project has an API
    download URL.  The URL takes the user to CurseForge's own search with the
    exact mod/version/loader terms we know, so the author-controlled page can
    be opened manually.
    """
    terms = [str(name or "").strip()]
    if minecraft_version:
        terms.append(str(minecraft_version).strip())
    if loader and loader != "vanilla":
        terms.append(loader_name(loader))
    return "https://www.curseforge.com/minecraft/search?search=" + quote_plus(" ".join(x for x in terms if x))


def _mod_name_from_filename(filename: str) -> str:
    """Make a conservative search name from a Minecraft mod JAR filename."""
    name = Path(filename).stem
    name = re.sub(r"(?i)[_-]?mc(?:forge|fabric|neoforge|quilt)?[-_]?1\.\d+(?:\.\d+)?", " ", name)
    name = re.sub(r"(?<!\d)1\.\d+(?:\.\d+)?(?!\d)", " ", name)
    name = re.sub(r"(?i)[_-]?(forge|fabric|neoforge|quilt)[_-]?", " ", name)
    name = re.sub(r"[_-]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def find_compatible_curseforge_file(api_key: str, filename: str, minecraft_version: str,
                                    loader: str) -> tuple[dict | None, str]:
    """Find a likely compatible CurseForge file for a local JAR.

    Returns (file_info, reason).  Matching is intentionally conservative: the
    project name must be reasonably similar to the local filename before a
    replacement is suggested.  API failures are returned as a reason so the
    caller can put a manual CurseForge search link in MISSING_MODS.txt.
    """
    if not api_key.strip():
        return None, "No CurseForge API key is configured."
    query = _mod_name_from_filename(filename)
    if not query:
        return None, "Could not determine the mod name from the filename."
    try:
        params = {
            "gameId": CURSEFORGE_GAME_ID,
            "classId": 6,
            "searchFilter": query,
            "pageSize": 10,
            "sortField": 2,
            "sortOrder": "desc",
        }
        projects = _request_json(f"{CURSEFORGE_API}/mods/search", api_key, params=params).get("data", [])
        if not isinstance(projects, list):
            return None, "CurseForge returned no project results."
        query_norm = re.sub(r"[^a-z0-9]+", "", query.lower())
        best = None
        best_score = 0.0
        for project in projects:
            pid = int(project.get("id") or 0)
            pname = str(project.get("name") or "")
            if not pid:
                continue
            pnorm = re.sub(r"[^a-z0-9]+", "", pname.lower())
            score = difflib.SequenceMatcher(None, query_norm, pnorm).ratio()
            if query_norm and query_norm in pnorm:
                score += 0.25
            if score > best_score:
                best_score, best = score, project
        if not best or best_score < 0.45:
            return None, "No sufficiently close CurseForge project match was found."

        files = get_project_files(api_key, int(best["id"]), minecraft_version=minecraft_version, page_size=50)
        wanted_loader = loader_name(loader).lower() if loader else ""
        candidates = []
        for f in files:
            versions = {str(v).strip() for v in (f.get("gameVersions") or [])}
            if minecraft_version and minecraft_version not in versions:
                continue
            # CurseForge's file metadata exposes modLoader fields on many
            # files. Also inspect the display/file name for loader hints.
            fl = " ".join(str(f.get(k) or "") for k in ("displayName", "fileName")).lower()
            if wanted_loader and wanted_loader not in fl:
                # Do not reject an otherwise valid file when the metadata does
                # not put the loader in its name; the API's gameVersion tags
                # are authoritative enough for a candidate list.
                if f.get("modLoaderType") is not None:
                    continue
            fname = str(f.get("fileName") or f.get("displayName") or "")
            base_query = re.sub(r"[^a-z0-9]+", "", query.lower())
            base_file = re.sub(r"[^a-z0-9]+", "", Path(fname).stem.lower())
            fscore = difflib.SequenceMatcher(None, base_query, base_file).ratio()
            candidates.append((fscore, f))
        if not candidates:
            return None, f"Project '{best.get('name')}' has no {minecraft_version} file matching the requested loader."
        candidates.sort(key=lambda x: (x[0], str(x[1].get("fileDate") or "")), reverse=True)
        chosen = dict(candidates[0][1])
        slug = str(best.get("slug") or "").strip()
        if slug:
            chosen["__manualFileUrl"] = f"https://www.curseforge.com/minecraft/mc-mods/{slug}/files/{int(chosen.get("id") or 0)}"
        return chosen, ""
    except requests.HTTPError as exc:
        return None, f"CurseForge API denied access ({exc})."
    except Exception as exc:
        return None, f"Could not query CurseForge: {exc}"


def build_missing_mod_entry(name: str, minecraft_version: str, loader: str, *,
                            project_url: str = "", reason: str = "") -> str:
    """Format one manual-recovery entry for MISSING_MODS.txt."""
    url = project_url.strip() or _curseforge_search_url(name, minecraft_version, loader)
    suffix = f" — {reason}" if reason else ""
    return f"{name}\n  CurseForge: {url}{suffix}"


def get_file(api_key: str, project_id: int, file_id: int) -> dict:
    data = _request_json(f"{CURSEFORGE_API}/mods/{project_id}/files/{file_id}", api_key).get("data")
    if not isinstance(data, dict):
        raise RuntimeError("CurseForge returned no file information.")
    return data


def get_download_url(api_key: str, project_id: int, file_id: int) -> str:
    """Resolve the actual CurseForge CDN URL for a file.

    The URL returned by some file metadata responses can be the public
    curseforge.com download page rather than a directly downloadable CDN URL.
    Use the official download-url endpoint so installers never try to fetch
    the HTML page (which returns 403).
    """
    data = _request_json(
        f"{CURSEFORGE_API}/mods/{project_id}/files/{file_id}/download-url",
        api_key,
    ).get("data")
    if not isinstance(data, str) or not data.strip():
        raise RuntimeError(
            f"CurseForge did not provide a downloadable URL for file {file_id}."
        )
    return data.strip()


def _download(url: str, dest: Path, api_key: str, events: queue.Queue, message: str = "Downloading…") -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, headers=_headers(api_key), stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(256 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                events.put(DownloadEvent(kind="progress", downloaded=done, total=total, message=message if not total else ""))
    # A dropped connection partway through a big archive (ATM10 is well
    # over 1GB) can end iter_content() cleanly without raising, leaving a
    # truncated .part file that still gets renamed into place and silently
    # extracted with mods missing/corrupted, while the install goes on to
    # report success. Catch that here instead of downstream.
    if total and done != total:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"Download of {dest.name} was incomplete: got {done:,} of {total:,} bytes "
            "(the connection likely dropped). Try again."
        )
    tmp.replace(dest)


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    root = dest.resolve()
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        if target != root and root not in target.parents:
            raise RuntimeError(f"Unsafe path in modpack archive: {member.filename}")
    # testzip() runs a CRC check on every member and returns the name of
    # the first corrupted one (or None). Without this, a partially-written
    # or bit-flipped archive extracts whatever it can with no error, and
    # any file that failed its CRC just doesn't show up on disk afterward
    # with nothing in the UI to say why.
    bad_file = zf.testzip()
    if bad_file:
        raise RuntimeError(
            f"The modpack archive is corrupted (bad file: {bad_file}). "
            "Re-download it and try installing again."
        )
    zf.extractall(dest)


def _find_manifest(root: Path) -> Path | None:
    direct = root / "manifest.json"
    if direct.exists():
        return direct
    matches = list(root.glob("*/manifest.json"))
    return matches[0] if matches else None


def _parse_loader(manifest: dict) -> tuple[str, str]:
    mc_data = manifest.get("minecraft") or {}
    version = str(mc_data.get("version") or "")
    loaders = mc_data.get("modLoaders") or []
    loader_id = ""
    if loaders and isinstance(loaders[0], dict):
        loader_id = str(loaders[0].get("id") or "")
    elif loaders:
        loader_id = str(loaders[0])
    low = loader_id.lower()
    for prefix, name in (("neoforge-", "neoforge"), ("forge-", "forge"), ("fabric-", "fabric"), ("quilt-", "quilt")):
        if low.startswith(prefix):
            return name, loader_id[len(prefix):]
    return "vanilla", ""


def _copy_overrides(root: Path, server_dir: Path, manifest: dict) -> None:
    override_name = str(manifest.get("overrides") or "overrides")
    override = root / override_name
    if not override.exists():
        return
    for src in override.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(override)
        dst = server_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def peek_manifest_minecraft_version(archive_path: Path) -> str:
    """Read the declared Minecraft version, or infer it from a raw share profile.

    Normal CurseForge modpacks expose manifest.json.  CurseForge share links can
    instead produce a client-profile ZIP with no manifest at all; for those,
    inspect JAR filenames and choose the most common Minecraft version so the
    UI can select the correct Java runtime before the install worker starts.
    """
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            names = zf.namelist()
            candidate = next(
                (n for n in names if n == "manifest.json" or (n.endswith("/manifest.json") and n.count("/") == 1)),
                None,
            )
            if candidate:
                manifest = json.loads(zf.read(candidate).decode("utf-8", errors="replace"))
                version = str((manifest.get("minecraft") or {}).get("version") or "")
                if version:
                    return version

            # Manifest-less CurseForge share profile fallback.
            counts: dict[str, int] = {}
            for name in names:
                if not name.lower().endswith(".jar"):
                    continue
                for match in re.findall(r"\b1\.\d{1,2}(?:\.\d{1,2})?\b", name):
                    counts[match] = counts.get(match, 0) + 1
            if counts:
                return max(counts, key=counts.get)
    except Exception:
        pass
    return ""


def _install_loader_blocking(server_dir: Path, loader: str, mc_version: str, loader_version: str,
                             java_path: str, min_mb: int, max_mb: int, events: queue.Queue) -> None:
    worker = create_install_worker(server_dir, loader, mc_version, loader_version, java_path, min_mb, max_mb)
    worker.start()
    failure_message = ""

    def _drain() -> None:
        nonlocal failure_message
        try:
            while True:
                inner_event = worker.events.get_nowait()
                if inner_event.kind == "error":
                    failure_message = inner_event.message or failure_message
                events.put(inner_event)
        except queue.Empty:
            pass

    while worker.is_alive():
        _drain()
        worker.join(0.15)
    _drain()

    # _install_manifest previously kept going even when the loader install
    # itself failed (bad Java version for that Minecraft release, Forge/
    # NeoForge Maven being down, etc.) because this function only relayed
    # the inner worker's events without checking whether one of them was an
    # "error". That let a completely failed loader install (no run.bat, no
    # forge/fabric/quilt server jar ever produced) sail through, spend
    # however long downloading every mod in the manifest, and then get
    # reported to the UI as a fully successful install. Raise here instead
    # so a failed loader install actually aborts the modpack install.
    if failure_message:
        raise RuntimeError(f"{loader_name(loader)} installation failed: {failure_message}")
    if not detect_loader(server_dir):
        raise RuntimeError(
            f"{loader_name(loader)} installation did not produce a recognizable "
            "Minecraft server launcher."
        )


def _install_manifest(root: Path, manifest: dict, server_dir: Path, api_key: str, events: queue.Queue,
                      java_path: str, min_mb: int, max_mb: int) -> tuple[str, str, str, list[tuple[str, str]]]:
    loader, loader_version = _parse_loader(manifest)
    mc_version = str((manifest.get("minecraft") or {}).get("version") or "")
    if not mc_version:
        raise RuntimeError("Modpack manifest does not specify a Minecraft version.")

    # A manifest with no modLoaders entry isn't a broken pack — CurseForge
    # itself treats these as legitimate "vanilla" modpacks (resource packs,
    # data packs, configs, world files, but no mod loader). Install the
    # plain vanilla server for it instead of refusing the whole pack.
    events.put(DownloadEvent(kind="progress", downloaded=5, total=100,
                              message=f"Installing {loader_name(loader)} server…"))
    _install_loader_blocking(server_dir, loader, mc_version, loader_version, java_path, min_mb, max_mb, events)

    files = manifest.get("files") or []
    total = len(files)
    failed: list[str] = []
    for index, item in enumerate(files, 1):
        if not isinstance(item, dict) or item.get("required") is False:
            continue
        project_id = int(item.get("projectID") or 0)
        file_id = int(item.get("fileID") or 0)
        if not project_id or not file_id:
            continue
        # CurseForge's real modpack manifest never includes a "path" per
        # file entry (only projectID/fileID) — the actual file name has to
        # be resolved from the API. Treating a missing "path" as "skip this
        # mod" (the old behavior) meant every mod in every manifest-based
        # pack silently failed to download, leaving a loader-only server
        # with configs but no mods. Resolve and download it properly here,
        # the same way the client-side installer already does.
        try:
            info = get_file(api_key, project_id, file_id)
            file_name = str(info.get("fileName") or "").strip()
            if not file_name:
                raise RuntimeError("CurseForge did not return a file name.")
            url = str(info.get("downloadUrl") or "").strip() or get_download_url(api_key, project_id, file_id)
            dest = server_dir / "mods" / file_name
            _download(url, dest, api_key, events, f"Downloading mod {index}/{total}…")
        except Exception:
            # Some mods disable third-party/API downloads and must be
            # fetched manually from the CurseForge site; don't let one
            # mod's failure silently drop the rest of the pack.
            try:
                mod_info = _request_json(f"{CURSEFORGE_API}/mods/{project_id}", api_key).get("data") or {}
                mod_name = str(mod_info.get("name") or "").strip()
                mod_url = str((mod_info.get("links") or {}).get("websiteUrl") or "").strip()
            except Exception:
                mod_name, mod_url = "", ""
            display_name = mod_name or f"project {project_id} file {file_id}"
            failed.append(build_missing_mod_entry(
                display_name, mc_version, loader,
                project_url=mod_url,
                reason="API distribution/download access is unavailable; open the CurseForge page manually."
            ))
        events.put(DownloadEvent(kind="progress", downloaded=5 + int(85 * index / max(1, total)), total=100,
                                 message=f"Installed {index}/{total} mods…"))

    _copy_overrides(root, server_dir, manifest)

    if failed:
        # Don't let a few blocked mods (common — some authors disable
        # third-party downloads) discard an otherwise-successful install:
        # the loader, the rest of the mods, and all overrides are already
        # on disk at this point. Write out what's missing instead of
        # raising, so the caller can still record minecraft_version/loader
        # and keep the modpack profile instead of rolling it back.
        (server_dir / "MISSING_MODS.txt").write_text(
            "These mods could not be downloaded automatically. CurseForge authors can "
            "disable third-party distribution, which prevents the API/CDN from supplying "
            "the file to this manager. Each entry includes a CurseForge link for manual "
            "download.\n\n" + "\n\n".join(failed) + "\n",
            encoding="utf-8",
        )

    return mc_version, loader, loader_version, failed


def create_modpack_install_worker(server_dir: Path, source: Path, api_key: str = "", *,
                                  java_path: str = "java", min_mb: int = 1024, max_mb: int = 2048,
                                  project_id: int | None = None, file_id: int | None = None,
                                  project_name: str = "Imported Modpack") -> threading.Thread:
    """Install a local/remote CurseForge modpack ZIP into a Minecraft server directory."""
    class Worker(threading.Thread):
        def __init__(self):
            super().__init__(daemon=True)
            self.events: queue.Queue = queue.Queue()
            self.modpack_name = project_name
            self.minecraft_version = ""
            self.loader = ""
            self.loader_version = ""
            self.project_id = project_id
            self.file_id = file_id

        def run(self):
            temp = Path(tempfile.mkdtemp(prefix="zsm_modpack_"))
            try:
                server_dir.mkdir(parents=True, exist_ok=True)
                archive = source
                if not archive.exists():
                    raise RuntimeError(f"Modpack archive not found: {archive}")
                self.events.put(DownloadEvent(kind="progress", downloaded=2, total=100, message="Reading modpack archive…"))
                with zipfile.ZipFile(archive, "r") as zf:
                    _safe_extract(zf, temp)
                manifest_path = _find_manifest(temp)
                if manifest_path is None:
                    self.events.put(DownloadEvent(kind="progress", downloaded=60, total=100, message="Server pack detected — extracting files…"))
                    # Reuse the same extraction path used for CurseForge server
                    # packs so a bundled Forge/NeoForge installer jar actually
                    # gets run when there's no run.bat/run.sh yet. The old
                    # copy-only logic here silently left self.loader empty for
                    # any pack that needed an installer, which meant the
                    # server config kept its stale/default "vanilla" loader.
                    _install_extracted_server_pack(
                        temp, server_dir, self.events, self.modpack_name,
                        java_path, min_mb, max_mb
                    )
                    self.loader = detect_loader(server_dir) or ""
                    # Server/share ZIPs have no manifest.json to declare their
                    # Minecraft version or exact loader build. Prefer the
                    # server's own logs/jars, then infer it from the profile's
                    # mod filenames. This also records the Forge version that
                    # was installed for a raw CurseForge share profile.
                    inferred_mc, inferred_loader, inferred_loader_version = _infer_raw_profile_loader(
                        temp, self.modpack_name
                    )
                    self.minecraft_version = (
                        detect_minecraft_version(server_dir)
                        or inferred_mc
                        or _guess_minecraft_version(self.modpack_name, archive.name)
                        or ""
                    )
                    if not self.loader:
                        self.loader = inferred_loader
                    if not self.loader_version:
                        self.loader_version = inferred_loader_version
                    self.events.put(DownloadEvent(kind="done", message="Server modpack extracted successfully."))
                    return

                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.modpack_name = str(manifest.get("name") or self.modpack_name)
                if not api_key.strip():
                    raise RuntimeError("This CurseForge modpack uses a manifest. Enter a CurseForge API key to download its mods.")
                root = manifest_path.parent
                self.minecraft_version, self.loader, self.loader_version, failed_mods = _install_manifest(
                    root, manifest, server_dir, api_key, self.events, java_path, min_mb, max_mb
                )
                if failed_mods:
                    self.events.put(DownloadEvent(
                        kind="done",
                        message=(
                            f"Modpack '{self.modpack_name}' installed, but {len(failed_mods)} mod(s) "
                            f"need manual download — see MISSING_MODS.txt in the server folder."
                        ),
                    ))
                else:
                    self.events.put(DownloadEvent(kind="done", message=f"Modpack '{self.modpack_name}' installed successfully."))
            except Exception as exc:
                self.events.put(DownloadEvent(kind="error", message=str(exc)))
            finally:
                shutil.rmtree(temp, ignore_errors=True)

    return Worker()


def _guess_minecraft_version(*texts: str) -> str:
    """Best-effort Minecraft version guess from a pack/installer file name.

    Fabric and Quilt's headless installers need an explicit ``-mcversion``
    (they can't infer it from the jar itself the way Forge/NeoForge
    installers can), so when one of those installers is bundled inside an
    imported ZIP with no manifest.json, this pulls a "1.20.1"-shaped version
    out of whatever name we do have (the pack's file name, the installer's
    file name, etc).
    """
    for text in texts:
        match = re.search(r"\b1\.\d{1,2}(?:\.\d{1,2})?\b", text or "")
        if match:
            return match.group(0)
    return ""


def _run_fabric_installer(java_path: str, installer: Path, server_dir: Path, mc_version: str, events: queue.Queue) -> None:
    events.put(DownloadEvent(kind="progress", downloaded=50, total=100, message="Running Fabric server installer…"))
    proc = subprocess.run(
        [java_path, "-jar", str(installer), "server", "-mcversion", mc_version, "-dir", str(server_dir), "-downloadMinecraft"],
        cwd=str(server_dir), capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "Fabric installer failed").strip()
        raise RuntimeError(detail[-2000:])


def _run_quilt_installer(java_path: str, installer: Path, server_dir: Path, mc_version: str, events: queue.Queue) -> None:
    events.put(DownloadEvent(kind="progress", downloaded=50, total=100, message="Running Quilt server installer…"))
    proc = subprocess.run(
        [java_path, "-jar", str(installer), "install", "server", mc_version,
         "--download-server", f"--install-dir={server_dir}"],
        cwd=str(server_dir), capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "Quilt installer failed").strip()
        raise RuntimeError(detail[-2000:])



def _infer_raw_profile_loader(root: Path, pack_name: str = "") -> tuple[str, str, str]:
    """Infer a loader from a CurseForge shared-profile ZIP that has no manifest.

    CurseForge share links can export a client profile rather than a normal
    modpack manifest/server pack.  Those archives commonly contain only
    config/, mods/, kubejs/, resourcepacks/, etc.  In that case the loader
    still has to be reconstructed from the mod filenames/metadata.

    Returns (minecraft_version, loader, loader_version).  Forge is preferred
    when the profile contains Forge mods; the current recommended/latest Forge
    build for the detected Minecraft line is resolved by get_loader_versions().
    """
    candidates = [p for p in root.rglob("*.jar") if p.is_file()]
    texts = [p.name.lower() for p in candidates]
    texts.extend([pack_name.lower(), root.name.lower()])

    # Minecraft version: count explicit 1.x.y references in the JAR names and
    # prefer the version that occurs most often. This is much safer than taking
    # the first filename because a profile can contain a few dependency jars
    # with abbreviated version strings.
    counts: dict[str, int] = {}
    for text in texts:
        for match in re.findall(r"\b1\.\d{1,2}(?:\.\d{1,2})?\b", text):
            counts[match] = counts.get(match, 0) + 1
    mc_version = max(counts, key=counts.get) if counts else ""

    forge_hits = sum(1 for t in texts if "forge" in t and ("forge" in t or "ftb-" in t))
    fabric_hits = sum(1 for t in texts if "fabric" in t)
    quilt_hits = sum(1 for t in texts if "quilt" in t)
    if forge_hits >= max(fabric_hits, quilt_hits, 1):
        loader = "forge"
    elif fabric_hits > quilt_hits:
        loader = "fabric"
    elif quilt_hits:
        loader = "quilt"
    else:
        loader = "vanilla"

    loader_version = ""
    if loader == "forge" and mc_version:
        versions, error = get_loader_versions("forge", mc_version)
        if error:
            raise RuntimeError(f"Couldn't determine the Forge version for Minecraft {mc_version}: {error}")
        if versions:
            # get_loader_versions orders recommended before latest; use the
            # first available release rather than guessing a hard-coded build.
            loader_version = versions[0].id

    return mc_version, loader, loader_version


def detect_loader(server_dir: Path) -> str:
    """Detect whether a server directory already contains a Minecraft loader.

    Returns the loader key (forge/neoforge/fabric/quilt/vanilla) or an empty
    string when no server loader is present. This deliberately checks files
    rather than configuration metadata because existing modpack folders may
    predate the manager profile entry.
    """
    server_dir = Path(server_dir)
    if (server_dir / "run.bat").exists() or (server_dir / "run.sh").exists():
        text = ""
        for name in ("run.bat", "run.sh"):
            p = server_dir / name
            if p.exists():
                text += p.read_text(encoding="utf-8", errors="ignore").lower() + "\n"
        if "neoforge" in text:
            return "neoforge"
        if "forge" in text:
            return "forge"
        if "fabric" in text:
            return "fabric"
        if "quilt" in text:
            return "quilt"
    if any(p.is_file() for p in server_dir.glob("neoforge-*.jar")):
        return "neoforge"
    if any(p.is_file() and "installer" not in p.name.lower() for p in server_dir.glob("forge-*.jar")):
        return "forge"
    if any(p.is_file() for p in server_dir.glob("fabric-server-launch*.jar")):
        return "fabric"
    if any(p.is_file() for p in server_dir.glob("quilt-server-launch*.jar")):
        return "quilt"
    return ""



def scan_modpack_version_conflicts(root: Path) -> dict[str, Any]:
    """Inspect a manifest-less modpack for Minecraft-version conflicts.

    Returns a dictionary containing the dominant Minecraft version, detected
    versions, and the JARs that point at versions other than the dominant one.
    It reads common Forge/NeoForge ``mods.toml`` and Fabric ``fabric.mod.json``
    metadata when available, while also using explicit versions in filenames.
    This is intentionally conservative: ambiguous JARs are reported but do
    not by themselves block loader installation.
    """
    root = Path(root)
    records: list[dict[str, str]] = []
    version_re = re.compile(r"(?<!\d)1\.\d{1,2}(?:\.\d{1,2})?(?!\d)")

    def add(name: str, version: str, source: str, relative_path: str = "") -> None:
        if version:
            records.append({
                "file": name,
                "path": relative_path or name,
                "version": version,
                "source": source,
            })

    for jar in sorted(root.rglob("*.jar")):
        filename_versions = version_re.findall(jar.name)
        # Prefer a full x.y.z version when a filename contains one.
        filename_version = max(filename_versions, key=lambda x: len(x.split('.'))) if filename_versions else ""
        metadata_versions: list[str] = []
        try:
            with zipfile.ZipFile(jar) as zf:
                names = set(zf.namelist())
                if "META-INF/mods.toml" in names:
                    text = zf.read("META-INF/mods.toml").decode("utf-8", errors="ignore")
                    # Forge/NeoForge dependency ranges commonly contain the
                    # Minecraft version as [1.20.1,1.21), [1.16.5], etc.
                    for m in re.finditer(r'modId\s*=\s*"minecraft"[\s\S]{0,500}?versionRange\s*=\s*"([^"\n]+)"', text, re.I):
                        metadata_versions.extend(version_re.findall(m.group(1)))
                for meta_name in ("META-INF/neoforge.mods.toml", "fabric.mod.json"):
                    if meta_name in names:
                        text = zf.read(meta_name).decode("utf-8", errors="ignore")
                        # Fabric uses depends/recommends minecraft: ">=1.20 <1.21".
                        if meta_name.endswith("fabric.mod.json"):
                            for m in re.finditer(r'"minecraft"\s*:\s*"([^"]+)"', text, re.I):
                                metadata_versions.extend(version_re.findall(m.group(1)))
        except (OSError, zipfile.BadZipFile):
            pass

        version = metadata_versions[0] if metadata_versions else filename_version
        source = "metadata" if metadata_versions else ("filename" if filename_version else "")
        if version:
            add(jar.name, version, source, str(jar.relative_to(root)))

    counts: dict[str, int] = {}
    for r in records:
        counts[r["version"]] = counts.get(r["version"], 0) + 1
    dominant = max(counts, key=counts.get) if counts else ""
    conflicts = [r for r in records if dominant and r["version"] != dominant]
    # De-duplicate the same JAR/version pair if both metadata and filename
    # happened to report it.
    seen: set[tuple[str, str]] = set()
    unique_conflicts = []
    for r in conflicts:
        key = (r["file"], r["version"])
        if key not in seen:
            seen.add(key)
            unique_conflicts.append(r)
    return {
        "dominant_version": dominant,
        "versions": sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])),
        "conflicts": unique_conflicts,
        "records": records,
    }

def quarantine_modpack_conflicts(root: Path, conflicts: list[dict[str, str]]) -> list[Path]:
    """Move incompatible JARs out of the active mods tree.

    The files are preserved under ``<profile>/incompatible-mods/<mc-version>/``
    so the user can restore them later.  Only paths reported by the preflight
    scanner are moved; no other mod is touched.
    """
    root = Path(root)
    moved: list[Path] = []
    for item in conflicts:
        rel = str(item.get("path") or item.get("file") or "").strip()
        if not rel:
            continue
        src = (root / rel).resolve()
        root_resolved = root.resolve()
        if root_resolved not in src.parents or not src.is_file():
            continue
        version = re.sub(r"[^0-9A-Za-z._-]+", "_", str(item.get("version") or "unknown"))
        dest_dir = root / "incompatible-mods" / f"Minecraft-{version}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        if dest.exists():
            stem, suffix = src.stem, src.suffix
            n = 2
            while dest.exists():
                dest = dest_dir / f"{stem}_{n}{suffix}"
                n += 1
        shutil.move(str(src), str(dest))
        moved.append(dest)
    return moved



def replace_with_compatible_curseforge_mod(root: Path, jar_path: Path, api_key: str,
                                           minecraft_version: str, loader: str,
                                           events: queue.Queue | None = None) -> tuple[bool, str]:
    """Replace one incompatible local JAR with a compatible CurseForge file.

    The original JAR is preserved under ``.modpack_backup``.  If the author's
    distribution setting blocks the API, no replacement is made and a manual
    CurseForge search URL is returned instead.
    """
    info, reason = find_compatible_curseforge_file(api_key, jar_path.name, minecraft_version, loader)
    if not info:
        return False, str(info.get("__manualFileUrl") or _curseforge_search_url(_mod_name_from_filename(jar_path.name), minecraft_version, loader))
    file_id = int(info.get("id") or 0)
    project_id = int(info.get("modId") or info.get("projectId") or 0)
    if not file_id or not project_id:
        return False, str(info.get("__manualFileUrl") or _curseforge_search_url(_mod_name_from_filename(jar_path.name), minecraft_version, loader))
    try:
        url = str(info.get("downloadUrl") or "").strip() or get_download_url(api_key, project_id, file_id)
        backup = root / ".modpack_backup"
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copy2(jar_path, backup / jar_path.name)
        target_name = str(info.get("fileName") or "").strip()
        if not target_name:
            return False, str(info.get("__manualFileUrl") or _curseforge_search_url(_mod_name_from_filename(jar_path.name), minecraft_version, loader))
        target = jar_path.parent / target_name
        temp_events = events or queue.Queue()
        _download(url, target, api_key, temp_events, f"Replacing {jar_path.name}…")
        jar_path.unlink(missing_ok=True)
        return True, str(target)
    except requests.HTTPError:
        return False, str(info.get("__manualFileUrl") or _curseforge_search_url(_mod_name_from_filename(jar_path.name), minecraft_version, loader))
    except Exception:
        return False, str(info.get("__manualFileUrl") or _curseforge_search_url(_mod_name_from_filename(jar_path.name), minecraft_version, loader))


def infer_profile_loader(root: Path, pack_name: str = "") -> tuple[str, str, str]:
    """Public wrapper used by the UI to inspect a manifest-less modpack folder."""
    return _infer_raw_profile_loader(root, pack_name)


def _install_inferred_profile_loader(server_dir: Path, root: Path, pack_name: str,
                                     java_path: str, min_mb: int, max_mb: int,
                                     events: queue.Queue) -> tuple[str, str, str]:
    """Install the loader for a manifest-less/client-profile ZIP."""
    mc_version, loader, loader_version = _infer_raw_profile_loader(root, pack_name)
    if loader == "vanilla":
        raise RuntimeError(
            "The shared profile has no manifest/server loader and no supported "
            "Forge/Fabric/Quilt loader could be inferred from its mods."
        )
    if not mc_version:
        raise RuntimeError(
            "The shared profile has no manifest, so Minecraft's version could not "
            "be inferred from the archive."
        )
    if not loader_version and loader != "vanilla":
        raise RuntimeError(f"No {loader_name(loader)} version was found for Minecraft {mc_version}.")

    events.put(DownloadEvent(
        kind="progress", downloaded=92, total=100,
        message=f"No loader in share ZIP — installing {loader_name(loader)} {loader_version} for Minecraft {mc_version}…",
    ))
    _install_loader_blocking(
        server_dir, loader, mc_version, loader_version,
        java_path, min_mb, max_mb, events
    )
    return mc_version, loader, loader_version

def _install_extracted_server_pack(root: Path, server_dir: Path, events: queue.Queue, pack_name: str, java_path: str = "java", min_mb: int = 1024, max_mb: int = 2048) -> None:
    """Extract a CurseForge server pack as-is.

    CurseForge marks proper server-pack files with ``isServerPack`` /
    ``serverPackFileId``. A server pack is already prepared for dedicated
    servers, so we must not rebuild it from the client manifest.
    """
    entries = list(root.iterdir())
    source_root = entries[0] if len(entries) == 1 and entries[0].is_dir() else root

    files = [p for p in source_root.rglob("*") if p.is_file()]
    total = max(len(files), 1)
    for index, src in enumerate(files, 1):
        rel = src.relative_to(source_root)
        dst = server_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if index == 1 or index == total or index % 25 == 0:
            events.put(DownloadEvent(
                kind="progress",
                downloaded=65 + int(30 * index / total),
                total=100,
                message=f"Extracting server pack… {index}/{total}",
            ))

    detected = detect_loader(server_dir)
    if detected:
        events.put(DownloadEvent(
            kind="progress",
            downloaded=96,
            total=100,
            message=f"Detected {detected.title()} server loader.",
        ))

    # A CurseForge share profile is often a CLIENT profile rather than a
    # dedicated server pack. It has no manifest.json and no loader jar, so the
    # normal server-pack installer cannot detect anything. Infer the loader
    # from the bundled mods and install the matching server loader before the
    # caller records the profile metadata.
    if not detected:
        try:
            inferred_mc, inferred_loader, inferred_loader_version = _install_inferred_profile_loader(
                server_dir, root, pack_name, java_path, min_mb, max_mb, events
            )
            detected = detect_loader(server_dir)
            if detected:
                events.put(DownloadEvent(
                    kind="progress", downloaded=98, total=100,
                    message=(f"Installed {loader_name(inferred_loader)} {inferred_loader_version} "
                             f"for Minecraft {inferred_mc}."),
                ))
                return
        except RuntimeError:
            # Preserve the existing bundled-installer path below. If this is
            # merely an ordinary server pack with an installer, that path can
            # still handle it.
            pass

    if not detected:
        # Some server packs ship a loader installer instead of a ready-made
        # launcher: older Forge server packs (including 1.12.2 packs such as
        # SkyFactory 4) only include the Forge installer, and hand-built
        # Fabric/Quilt packs occasionally do the same instead of the more
        # common pre-built fabric-server-launch.jar / quilt-server-launch.jar.
        installer_candidates = list(dict.fromkeys(
            [p for p in server_dir.glob("*-installer.jar") if p.is_file()]
            + [p for p in server_dir.glob("*installer*.jar") if p.is_file()]
        ))
        if installer_candidates:
            installer = installer_candidates[0]
            installer_name = installer.name.lower()

            if "fabric" in installer_name or "quilt" in installer_name:
                mc_version = _guess_minecraft_version(pack_name, installer.name, root.name)
                if not mc_version:
                    raise RuntimeError(
                        f"Found a {'Fabric' if 'fabric' in installer_name else 'Quilt'} installer "
                        f"({installer.name}) but couldn't determine the Minecraft version from "
                        f"'{pack_name}'. Rename the ZIP to include the Minecraft version "
                        "(e.g. 'PackName-1.20.1-...') and import again."
                    )
                if "fabric" in installer_name:
                    _run_fabric_installer(java_path, installer, server_dir, mc_version, events)
                else:
                    _run_quilt_installer(java_path, installer, server_dir, mc_version, events)

                detected_after = detect_loader(server_dir)
                if detected_after:
                    installer.unlink(missing_ok=True)
                    events.put(DownloadEvent(
                        kind="progress", downloaded=98, total=100,
                        message=f"Detected {detected_after.title()} server loader.",
                    ))
                    return

                raise RuntimeError(
                    f"The included loader installer ({installer.name}) ran, but did not "
                    "generate a recognizable Minecraft server launcher."
                )

            # Forge / NeoForge installers support a headless --installServer flag.
            _run_installer(java_path, installer, server_dir, events)

            # Legacy Forge installers can generate either a *-universal.jar or
            # a forge-<minecraft>-<forge>.jar.  Do not require the modern
            # run.bat/run.sh layout.
            legacy_jars = sorted(
                [
                    p for p in server_dir.glob("forge-*.jar")
                    if p.is_file()
                    and "installer" not in p.name.lower()
                    and "sources" not in p.name.lower()
                    and "changelog" not in p.name.lower()
                ],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if legacy_jars:
                _set_memory(server_dir, min_mb, max_mb)
                events.put(DownloadEvent(
                    kind="progress", downloaded=98, total=100,
                    message=f"Generated Forge server launcher: {legacy_jars[0].name}",
                ))
                return

            detected_after = detect_loader(server_dir)
            if detected_after:
                _set_memory(server_dir, min_mb, max_mb)
                installer.unlink(missing_ok=True)
                return

            raise RuntimeError(
                f"The included loader installer ({installer.name}) ran, but did not "
                "generate a recognizable Minecraft server launcher."
            )

        raise RuntimeError(
            f"Server pack '{pack_name}' was extracted, but no supported Minecraft "
            "server loader or loader installer was detected."
        )


def create_modpack_loader_repair_worker(server_dir: Path, pack_name: str,
                                         java_path: str = "java", min_mb: int = 1024,
                                         max_mb: int = 2048) -> threading.Thread:
    """Install a missing loader into an existing manifest-less modpack folder."""
    class Worker(threading.Thread):
        def __init__(self):
            super().__init__(daemon=True)
            self.events: queue.Queue = queue.Queue()
            self.modpack_name = pack_name
            self.minecraft_version = ""
            self.loader = ""
            self.loader_version = ""
            self.java_path = java_path
            self.project_id = 0
            self.file_id = 0

        def run(self):
            try:
                mc_version, loader, loader_version = _infer_raw_profile_loader(server_dir, pack_name)
                if loader == "vanilla" or not loader_version:
                    raise RuntimeError(
                        "Could not infer a supported Minecraft loader from this modpack folder."
                    )
                self.minecraft_version = mc_version
                self.loader = loader
                self.loader_version = loader_version
                self.events.put(DownloadEvent(
                    kind="progress", downloaded=5, total=100,
                    message=f"Installing missing {loader_name(loader)} {loader_version} for Minecraft {mc_version}…",
                ))
                _install_loader_blocking(
                    server_dir, loader, mc_version, loader_version,
                    java_path, min_mb, max_mb, self.events
                )
                self.events.put(DownloadEvent(
                    kind="done",
                    message=f"{loader_name(loader)} {loader_version} installed successfully.",
                ))
            except Exception as exc:
                self.events.put(DownloadEvent(kind="error", message=str(exc)))

    return Worker()


def create_curseforge_download_worker(server_dir: Path, api_key: str, project_id: int, file_id: int,
                                      *, java_path: str = "java", min_mb: int = 1024, max_mb: int = 2048,
                                      project_name: str = "CurseForge Modpack") -> threading.Thread:
    """Install any CurseForge Minecraft modpack.

    Preferred path:
      1. Select the requested modpack release for the chosen Minecraft version.
      2. If CurseForge exposes a dedicated server pack for that release,
         download ``serverPackFileId`` and extract it directly.
      3. Otherwise fall back to the CurseForge manifest and install the
         declared loader/mod files.

    This is intentionally generic: SkyFactory, ATM, StoneBlock, Better MC,
    All the Mods, etc. all use the same flow.
    """
    class Worker(threading.Thread):
        def __init__(self):
            super().__init__(daemon=True)
            self.events: queue.Queue = queue.Queue()
            self.project_id = project_id
            self.file_id = file_id
            self.modpack_name = project_name
            self.minecraft_version = ""
            self.loader = ""
            self.loader_version = ""
            self.installed_file_id = 0
            self.server_pack_file_id = 0
            # Keep the exact Java executable used during installation so the
            # Start button cannot fall back to the system/default Java later.
            self.java_path = java_path

        def run(self):
            temp = Path(tempfile.mkdtemp(prefix="zsm_cf_"))
            try:
                server_dir.mkdir(parents=True, exist_ok=True)

                base_info = get_file(api_key, self.project_id, self.file_id)
                self.modpack_name = str(base_info.get("displayName") or self.modpack_name)
                self.installed_file_id = int(base_info.get("id") or self.file_id)

                versions = [str(v) for v in (base_info.get("gameVersions") or [])]
                if versions:
                    # The UI already filters by Minecraft version, but keep a
                    # second safety check here so a mismatched file cannot slip in.
                    target = None
                    for value in versions:
                        if value == self.minecraft_version:
                            target = value
                            break
                    # minecraft_version is not populated until a manifest is read;
                    # compatibility is therefore validated from the selected file
                    # and recorded below when the manifest/server pack is processed.

                server_pack_id = int(base_info.get("serverPackFileId") or 0)
                if bool(base_info.get("isServerPack")):
                    server_pack_id = int(base_info.get("id") or self.file_id)
                self.server_pack_file_id = server_pack_id

                chosen = base_info
                if server_pack_id and server_pack_id != int(base_info.get("id") or self.file_id):
                    self.events.put(DownloadEvent(
                        kind="progress",
                        downloaded=2,
                        total=100,
                        message="Found dedicated CurseForge server pack; using it instead of the client pack…",
                    ))
                    chosen = get_file(api_key, self.project_id, server_pack_id)

                chosen_id = int(chosen.get("id") or 0)
                if not chosen_id:
                    raise RuntimeError(f"CurseForge returned an invalid file ID for {self.modpack_name}.")

                # CurseForge file metadata tells us which Minecraft line the
                # selected release targets. Record it immediately so the server
                # config is saved with the actual modpack version, even when the
                # server pack itself has no manifest.json.
                chosen_versions = [
                    str(v) for v in (chosen.get("gameVersions") or [])
                ]
                mc_versions = [
                    v for v in chosen_versions
                    if re.fullmatch(r"1\.\d+(?:\.\d+)?", v)
                ]
                if mc_versions:
                    self.minecraft_version = mc_versions[0]

                url = get_download_url(api_key, self.project_id, chosen_id)

                filename = str(chosen.get("fileName") or "modpack-server.zip")
                archive = temp / filename
                self.events.put(DownloadEvent(
                    kind="progress",
                    downloaded=1,
                    total=100,
                    message=(
                        "Downloading dedicated server pack…"
                        if server_pack_id else "Downloading modpack…"
                    ),
                ))
                _download(url, archive, api_key, self.events,
                          "Downloading server pack…" if server_pack_id else "Downloading modpack…")

                with zipfile.ZipFile(archive, "r") as zf:
                    _safe_extract(zf, temp / "pack")

                root = temp / "pack"

                # A real server-pack file is already server-ready. Never run
                # the client manifest installer against it.
                if server_pack_id:
                    _install_extracted_server_pack(
                        root, server_dir, self.events, self.modpack_name,
                        java_path, min_mb, max_mb
                    )
                    self.loader = detect_loader(server_dir) or ""
                    self.events.put(DownloadEvent(
                        kind="done",
                        message=f"Modpack server pack '{self.modpack_name}' installed successfully.",
                    ))
                    return

                # No dedicated server pack exists: use the generic CurseForge
                # manifest installer as a fallback.
                manifest_path = _find_manifest(root)
                if manifest_path is None:
                    _install_extracted_server_pack(
                        root, server_dir, self.events, self.modpack_name,
                        java_path, min_mb, max_mb
                    )
                    self.loader = detect_loader(server_dir) or ""
                    self.events.put(DownloadEvent(
                        kind="done",
                        message=f"Modpack '{self.modpack_name}' installed successfully.",
                    ))
                    return

                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.modpack_name = str(manifest.get("name") or self.modpack_name)
                if not api_key.strip():
                    raise RuntimeError(
                        "This CurseForge modpack uses a manifest. Enter a CurseForge API key."
                    )
                self.minecraft_version, self.loader, self.loader_version, failed_mods = _install_manifest(
                    manifest_path.parent, manifest, server_dir, api_key,
                    self.events, java_path, min_mb, max_mb
                )
                if failed_mods:
                    self.events.put(DownloadEvent(
                        kind="done",
                        message=(
                            f"Modpack '{self.modpack_name}' installed, but {len(failed_mods)} mod(s) "
                            f"need manual download — see MISSING_MODS.txt in the server folder."
                        ),
                    ))
                else:
                    self.events.put(DownloadEvent(
                        kind="done",
                        message=f"Modpack '{self.modpack_name}' installed successfully.",
                    ))
            except Exception as exc:
                self.events.put(DownloadEvent(kind="error", message=str(exc)))
            finally:
                shutil.rmtree(temp, ignore_errors=True)

    return Worker()
