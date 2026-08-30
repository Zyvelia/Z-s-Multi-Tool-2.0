"""Minecraft client preparation and direct-launch helpers.

Prepares a real Minecraft/Forge client instance and, when a valid logged-in
Minecraft account token is available from the official launcher, starts the
game process directly without opening the Minecraft Launcher first.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

import requests

from .java_runtimes import is_32bit_jvm, max_settable_heap_mb

CURSEFORGE_API = "https://api.curseforge.com/v1"
MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
UA = "ZsMultiTool-GameServerManager/1.2"

# Populated by launch_minecraft_direct() with whatever max_settable_heap_mb()
# logged while verifying the heap for the most recent launch, so callers can
# surface *why* the applied heap doesn't match what was requested (rather
# than just showing the mismatch with no explanation).
_last_heap_probe_notes: list[str] = []


def get_last_heap_probe_notes() -> list[str]:
    return list(_last_heap_probe_notes)


def _cf_headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key.strip(), "User-Agent": UA, "Accept": "application/json"}


def _modpack_marker_path(client_dir: Path) -> Path:
    return client_dir / ".gsm_modpack_state.json"


def _modpack_already_installed(client_dir: Path, project_id: int, file_id: int) -> bool:
    marker = _modpack_marker_path(client_dir)
    if not marker.exists():
        return False
    try:
        state = json.loads(marker.read_text(encoding="utf-8"))
    except Exception:
        return False
    return int(state.get("project_id") or 0) == project_id and int(state.get("file_id") or 0) == file_id


def _mark_modpack_installed(client_dir: Path, project_id: int, file_id: int) -> None:
    _modpack_marker_path(client_dir).write_text(
        json.dumps({"project_id": project_id, "file_id": file_id}), encoding="utf-8"
    )


def _cf_json(url: str, api_key: str, **kwargs):
    r = requests.get(url, headers=_cf_headers(api_key), timeout=30, **kwargs)
    r.raise_for_status()
    return r.json()


def _cf_download_url(api_key: str, project_id: int, file_id: int) -> str:
    data = _cf_json(f"{CURSEFORGE_API}/mods/{project_id}/files/{file_id}/download-url", api_key).get("data")
    if not isinstance(data, str) or not data.strip():
        raise RuntimeError(f"CurseForge did not provide a download URL for client file {file_id}.")
    return data.strip()


def _is_server_pack(info: dict) -> bool:
    if info.get("serverPackFileId") or info.get("isServerPack"):
        return True
    name = str(info.get("displayName") or info.get("fileName") or "").lower()
    return "server pack" in name or "server files" in name or "_server_" in name or name.endswith("_server.zip")


def _find_client_file(api_key: str, project_id: int, mc_version: str, preferred_file_id: int = 0) -> dict:
    # First use the selected file if it is a real client pack.
    if preferred_file_id:
        try:
            info = _cf_json(f"{CURSEFORGE_API}/mods/{project_id}/files/{preferred_file_id}", api_key).get("data")
            if isinstance(info, dict) and not _is_server_pack(info):
                versions = [str(v) for v in (info.get("gameVersions") or [])]
                if not mc_version or mc_version in versions:
                    return info
        except Exception:
            pass

    # Do not require CurseForge's gameVersion filter. Older packs often have
    # incomplete metadata even though the client release is valid.
    data = _cf_json(
        f"{CURSEFORGE_API}/mods/{project_id}/files",
        api_key,
        params={"pageSize": 50, "index": 0},
    ).get("data") or []
    candidates = []
    for x in data:
        if not isinstance(x, dict) or _is_server_pack(x):
            continue
        versions = [str(v) for v in (x.get("gameVersions") or [])]
        if mc_version and versions and mc_version not in versions:
            continue
        if int(x.get("releaseType") or 1) != 1:
            continue
        candidates.append(x)
    candidates.sort(key=lambda x: str(x.get("fileDate") or ""), reverse=True)
    if not candidates:
        raise RuntimeError(f"Could not find a client modpack release for Minecraft {mc_version}.")
    return candidates[0]


class ModpackDownloadError(RuntimeError):
    """Raised when one or more modpack files could not be auto-downloaded.

    `entries` is a list of (label, url) tuples - url is "" when no
    CurseForge page could be resolved for that mod.
    """

    def __init__(self, message: str, entries: list[tuple[str, str]]):
        super().__init__(message)
        self.entries = entries


def _install_client_manifest(root: Path, manifest: dict, client_dir: Path, api_key: str) -> None:
    files = manifest.get("files") or []
    mods_dir = client_dir / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    failed: list[tuple[str, str]] = []
    for item in files:
        if not isinstance(item, dict) or item.get("required") is False:
            continue
        project_id = int(item.get("projectID") or 0)
        file_id = int(item.get("fileID") or 0)
        if not project_id or not file_id:
            continue
        try:
            info = _cf_json(f"{CURSEFORGE_API}/mods/{project_id}/files/{file_id}", api_key).get("data") or {}
            file_name = str(info.get("fileName") or "").strip()
            if not file_name:
                raise RuntimeError("CurseForge did not return a file name.")
            url = str(info.get("downloadUrl") or "").strip() or _cf_download_url(api_key, project_id, file_id)
            dest = mods_dir / file_name
            req = requests.get(url, headers={"User-Agent": UA}, stream=True, timeout=60)
            req.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in req.iter_content(256 * 1024):
                    if chunk:
                        f.write(chunk)
        except Exception:
            # Some mods disable third-party/API downloads and must be
            # fetched manually from the CurseForge site; don't let one
            # mod's failure silently drop the rest of the pack. The mod
            # info endpoint (unlike the file download) isn't blocked by
            # that restriction, so use it to give a human-readable pointer.
            try:
                mod_info = _cf_json(f"{CURSEFORGE_API}/mods/{project_id}", api_key).get("data") or {}
                mod_name = str(mod_info.get("name") or "").strip()
                mod_url = str((mod_info.get("links") or {}).get("websiteUrl") or "").strip()
            except Exception:
                mod_name, mod_url = "", ""
            if mod_name and mod_url:
                failed.append((mod_name, mod_url))
            elif mod_name:
                failed.append((mod_name, ""))
            else:
                failed.append((f"project {project_id} file {file_id}", ""))

    override_name = str(manifest.get("overrides") or "overrides")
    override = root / override_name
    if override.exists():
        for src in override.rglob("*"):
            if src.is_file():
                dst = client_dir / src.relative_to(override)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

    if failed:
        lines = [f"{name} ({url})" if url else name for name, url in failed]
        preview = "\n".join(f"- {x}" for x in lines[:15])
        more = f"\n- and {len(lines) - 15} more" if len(lines) > 15 else ""
        raise ModpackDownloadError(
            f"{len(failed)} mod(s) could not be downloaded automatically (often because the "
            f"author disabled third-party downloads on CurseForge) and must be added manually "
            f"to {mods_dir}:\n{preview}{more}",
            entries=failed,
        )


def minecraft_dir() -> Path:
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / ".minecraft"
    return Path.home() / ".minecraft"


def find_launcher() -> Path | None:
    candidates: list[Path] = []
    if platform.system() == "Windows":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pfx86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        candidates += [
            Path(pf) / "Minecraft Launcher" / "MinecraftLauncher.exe",
            Path(pfx86) / "Minecraft Launcher" / "MinecraftLauncher.exe",
            Path(local) / "Programs" / "Minecraft Launcher" / "MinecraftLauncher.exe",
            Path(local) / "Minecraft Launcher" / "MinecraftLauncher.exe",
        ]
    return next((p for p in candidates if p.exists()), None)


def _download(url: str, dest: Path) -> None:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=120) as r:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.read())


def _run_installer(java: str, installer: Path, mc_dir: Path) -> None:
    proc = subprocess.run(
        [java, "-jar", str(installer), "--installClient", str(mc_dir)],
        cwd=str(mc_dir), capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"Forge client installation failed (code {proc.returncode}). {detail[-1200:]}")


def _server_mods_populated(server_dir: Path) -> bool:
    """True if the server directory already has actual mod jars on disk.

    When someone has copied mods in manually (e.g. from their CurseForge
    client instance) rather than relying on the CurseForge API, launching
    should just use those files directly instead of trying to re-fetch
    everything from CurseForge (which needs a valid project/file id and an
    API key, and may hit mods that block third-party downloads).
    """
    mods_dir = server_dir / "mods"
    return mods_dir.is_dir() and any(mods_dir.glob("*.jar"))


def _copy_client_files(server_dir: Path, client_dir: Path) -> None:
    for name in ("mods", "config", "defaultconfigs", "kubejs", "scripts", "resourcepacks", "shaderpacks"):
        src = server_dir / name
        if not src.exists():
            continue
        dst = client_dir / name
        if dst.exists():
            shutil.rmtree(dst)
        if src.is_dir():
            shutil.copytree(src, dst)


def _write_profile(mc_dir: Path, profile_id: str, name: str, version_id: str, game_dir: Path) -> None:
    path = mc_dir / "launcher_profiles.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        data = {}
    profiles = data.setdefault("profiles", {})
    profiles[profile_id] = {
        "name": name, "type": "custom", "lastVersionId": version_id, "gameDir": str(game_dir),
    }
    data["selectedProfile"] = profile_id
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _library_maven_key(lib: dict) -> str:
    """Return a library's "group:artifact" coordinate (version-agnostic)."""
    parts = str(lib.get("name") or "").split(":")
    return ":".join(parts[:2]) if len(parts) >= 2 else str(lib.get("name") or "")


def _merge_version_metadata(parent: dict, child: dict) -> dict:
    """Merge Mojang/loader version metadata, including modern inheritsFrom."""
    merged = dict(parent)
    for key, value in child.items():
        if key in {"inherits", "inheritsFrom"}:
            continue
        if key == "libraries":
            parent_libs = list(parent.get("libraries") or [])
            child_libs = list(value or [])
            # Loaders like Forge/NeoForge intentionally pin newer versions of
            # some libraries than vanilla ships (most notably log4j-core, for
            # TerminalConsoleAppender/Mixin). A plain concatenation put both
            # versions on the classpath, and since vanilla's older jar came
            # first the JVM resolved classes from it, causing
            # "NoSuchMethodError: ThrowablePatternConverter.<init>" at launch.
            # Drop any vanilla library the child overrides by the same
            # group:artifact coordinate so only the loader's version remains.
            child_keys = {
                _library_maven_key(lib) for lib in child_libs if isinstance(lib, dict)
            }
            merged[key] = [
                lib for lib in parent_libs
                if not (isinstance(lib, dict) and _library_maven_key(lib) in child_keys)
            ] + child_libs
        elif key == "arguments" and isinstance(value, dict):
            args = dict(parent.get("arguments") or {})
            for section in ("jvm", "game"):
                pv = list(args.get(section) or [])
                cv = list(value.get(section) or [])
                if pv or cv:
                    args[section] = pv + cv
            for k, v in value.items():
                if k not in {"jvm", "game"}:
                    args[k] = v
            merged[key] = args
        else:
            merged[key] = value
    return merged


def _version_json(mc_dir: Path, version_id: str) -> tuple[dict, Path]:
    p = mc_dir / "versions" / version_id / f"{version_id}.json"
    if not p.exists():
        raise RuntimeError(f"Minecraft version metadata is missing: {version_id}")
    data = json.loads(p.read_text(encoding="utf-8"))

    # Forge commonly uses "inherits"; modern NeoForge uses "inheritsFrom".
    # Resolve the chain recursively so NeoForge 1.20+ / 1.21.x receives the
    # vanilla client libraries, assets and arguments it inherits from.
    parent_id = data.get("inherits") or data.get("inheritsFrom")
    if parent_id:
        parent_id = str(parent_id)
        parent_path = mc_dir / "versions" / parent_id / f"{parent_id}.json"
        if not parent_path.exists():
            _ensure_vanilla_version(mc_dir, parent_id)
        parent_data, _ = _version_json(mc_dir, parent_id)
        data = _merge_version_metadata(parent_data, data)
        # The merge above drops "inherits"/"inheritsFrom" (they're loader-chain
        # bookkeeping, not real client metadata) and lets the child's own "id"
        # win, so callers checking data["inherits"] to find the vanilla jar/
        # manifest entry would otherwise see None and fall back to the loader's
        # id (e.g. "1.16.5-forge-36.2.34") instead of the real "1.16.5". Restore
        # it, resolved all the way up the chain to the true vanilla ancestor.
        data["inherits"] = parent_data.get("inherits") or parent_id
    return data, p


def _ensure_vanilla_version(mc_dir: Path, mc_version: str) -> None:
    manifest = requests.get(MOJANG_MANIFEST, headers={"User-Agent": UA}, timeout=30)
    manifest.raise_for_status()
    item = next((v for v in manifest.json().get("versions", []) if v.get("id") == mc_version), None)
    if not item:
        raise RuntimeError(f"Minecraft {mc_version} was not found in Mojang's version manifest.")
    vdir = mc_dir / "versions" / mc_version
    vjson = vdir / f"{mc_version}.json"
    if not vjson.exists():
        data = requests.get(item["url"], headers={"User-Agent": UA}, timeout=30)
        data.raise_for_status()
        vdir.mkdir(parents=True, exist_ok=True)
        vjson.write_text(json.dumps(data.json(), indent=2), encoding="utf-8")
    info = json.loads(vjson.read_text(encoding="utf-8"))
    client = vdir / f"{mc_version}.jar"
    if not client.exists() and info.get("downloads", {}).get("client", {}).get("url"):
        _download(info["downloads"]["client"]["url"], client)

    assets = info.get("assetIndex") or {}
    if assets.get("id") and assets.get("url"):
        idx = mc_dir / "assets" / "indexes" / f"{assets['id']}.json"
        if not idx.exists():
            _download(assets["url"], idx)
        try:
            idx_data = json.loads(idx.read_text(encoding="utf-8"))
            objects = idx_data.get("objects") or {}

            # Download missing assets concurrently.  A 1.21.x client can have
            # thousands of small asset objects; doing them serially made the
            # UI appear stuck on "Preparing..." for a very long time.
            from concurrent.futures import ThreadPoolExecutor, as_completed

            pending = []
            for obj in objects.values():
                h = obj.get("hash")
                if not h:
                    continue
                dest = mc_dir / "assets" / "objects" / h[:2] / h
                if not dest.exists():
                    pending.append((h, dest))

            def fetch_asset(item):
                h, dest = item
                _download(f"https://resources.download.minecraft.net/{h[:2]}/{h}", dest)
                return h

            if pending:
                workers = min(16, max(4, (os.cpu_count() or 4) * 2))
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(fetch_asset, item) for item in pending]
                    for future in as_completed(futures):
                        try:
                            future.result()
                        except Exception:
                            # A transient asset failure should not prevent the
                            # game from launching; missing assets can be retried
                            # on the next Play Modpack attempt.
                            pass
        except Exception:
            pass


def _library_allowed(lib: dict, features: dict[str, bool] | None = None) -> bool:
    rules = lib.get("rules") or []
    if not rules:
        return True
    allowed = False
    os_name = "windows" if platform.system() == "Windows" else ("osx" if platform.system() == "Darwin" else "linux")
    features = features or {}
    for rule in rules:
        action = rule.get("action")
        if action == "allow":
            allowed = True
            if rule.get("os", {}).get("name") not in (None, os_name):
                allowed = False
            for feat_name, feat_required in (rule.get("features") or {}).items():
                if bool(feat_required) != bool(features.get(feat_name)):
                    allowed = False
        elif action == "disallow":
            osrule = rule.get("os", {}).get("name")
            if osrule in (None, os_name):
                allowed = False
    return allowed


def _maven_path(name: str) -> str:
    parts = name.split(":")
    if len(parts) < 3:
        return ""
    group, artifact, version = parts[:3]
    classifier = parts[3] if len(parts) > 3 else ""
    ext = parts[4] if len(parts) > 4 else "jar"
    rel = f"{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}"
    if classifier:
        rel += f"-{classifier}"
    return rel + f".{ext}"


def _ensure_libraries(mc_dir: Path, libs: list[dict], natives_dir: Path) -> list[Path]:
    out: list[Path] = []
    seen = set()
    for lib in libs:
        if not isinstance(lib, dict) or not _library_allowed(lib):
            continue
        downloads = lib.get("downloads") or {}
        artifact = downloads.get("artifact") or {}
        path = artifact.get("path") or _maven_path(str(lib.get("name") or ""))
        if path:
            local = mc_dir / "libraries" / path
            if not local.exists():
                url = artifact.get("url") or f"https://libraries.minecraft.net/{path}"
                try:
                    _download(url, local)
                except Exception as exc:
                    raise RuntimeError(f"Could not download Minecraft library {path}: {exc}") from exc
            if local.exists() and str(local).lower() not in seen:
                out.append(local)
                seen.add(str(local).lower())

        natives = lib.get("natives") or {}
        classifiers = downloads.get("classifiers") or {}
        if natives:
            os_key = "windows" if platform.system() == "Windows" else ("osx" if platform.system() == "Darwin" else "linux")
            classifier = natives.get(os_key)
            if classifier:
                native_info = classifiers.get(classifier) or {}
                npath = native_info.get("path")
                if npath:
                    native = mc_dir / "libraries" / npath
                    if not native.exists() and native_info.get("url"):
                        _download(native_info["url"], native)
                    if native.exists():
                        with zipfile.ZipFile(native) as zf:
                            for member in zf.namelist():
                                if not member or member.endswith("/"):
                                    continue
                                if member.startswith("META-INF/"):
                                    continue
                                target = natives_dir / Path(member).name
                                target.parent.mkdir(parents=True, exist_ok=True)
                                with zf.open(member) as src, open(target, "wb") as dst:
                                    shutil.copyfileobj(src, dst)
    return out


def _launcher_account_from_json(data: dict) -> dict | None:
    """Extract a usable Java account from modern or legacy launcher JSON.

    The website-installed Minecraft Launcher and the Microsoft Store build do
    not always use the same JSON schema.  Modern builds normally use
    launcher_accounts.json; older/alternate builds can expose the same cached
    session through launcher_profiles*.json under authenticationDatabase.
    """
    if not isinstance(data, dict):
        return None

    # Modern launcher_accounts.json.
    accounts = data.get("accounts")
    if isinstance(accounts, dict):
        active = data.get("activeAccountUuid") or data.get("activeAccount")
        ordered = []
        if active and isinstance(accounts.get(active), dict):
            ordered.append(accounts[active])
        ordered.extend(v for k, v in accounts.items() if k != active and isinstance(v, dict))
        for acc in ordered:
            prof = acc.get("minecraftProfile")
            prof = prof if isinstance(prof, dict) else {}
            token = str(acc.get("accessToken") or "").strip()
            uid = str(prof.get("id") or "").replace("-", "").strip()
            name = str(prof.get("name") or "").strip()
            if token and uid and name:
                return {"accessToken": token, "uuid": uid, "name": name, "userType": "msa"}

    # Legacy Java launcher_profiles*.json.
    auth_db = data.get("authenticationDatabase")
    if isinstance(auth_db, dict):
        selected = data.get("selectedUser")
        selected_uuid = ""
        if isinstance(selected, dict):
            selected_uuid = str(selected.get("account") or selected.get("uuid") or "").strip()

        ordered = []
        if selected_uuid and isinstance(auth_db.get(selected_uuid), dict):
            ordered.append(auth_db[selected_uuid])
        ordered.extend(v for k, v in auth_db.items() if k != selected_uuid and isinstance(v, dict))

        for acc in ordered:
            token = str(acc.get("accessToken") or acc.get("access_token") or "").strip()
            profiles = acc.get("profiles")
            if not isinstance(profiles, dict):
                profiles = {}
            for pid, prof in profiles.items():
                if not isinstance(prof, dict):
                    continue
                uid = str(prof.get("id") or pid).replace("-", "").strip()
                name = str(prof.get("displayName") or prof.get("name") or "").strip()
                if token and uid and name:
                    return {"accessToken": token, "uuid": uid, "name": name, "userType": "msa"}
    return None


def _get_account() -> dict | None:
    """Return the manager's Microsoft-authenticated Minecraft account.

    First use an account signed into Z's Multi Tool. If that is not available,
    discover an already authenticated account from the official Minecraft
    Launcher.  This supports both the website-installed launcher and the
    Microsoft Store launcher layouts.
    """
    try:
        from .minecraft_auth import get_account
        account = get_account(refresh=True)
        if account and account.get("minecraft_token") and account.get("uuid") and account.get("name"):
            return {
                "accessToken": account["minecraft_token"],
                "uuid": str(account["uuid"]).replace("-", ""),
                "name": account["name"],
                "userType": "msa",
            }
    except Exception:
        pass

    base = minecraft_dir()
    candidates = [
        # Website-installed/current launcher.
        base / "launcher_accounts.json",
        base / "launcher_profiles.json",
        base / "launcher_profiles_microsoft_store.json",
    ]

    if platform.system() == "Windows":
        appdata = Path(os.environ.get("APPDATA", ""))
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        # Explicit AppData paths, including the Microsoft Store launcher.
        candidates += [
            appdata / ".minecraft" / "launcher_accounts.json",
            appdata / ".minecraft" / "launcher_profiles.json",
            appdata / ".minecraft" / "launcher_profiles_microsoft_store.json",
        ]
        package = local / "Packages" / "Microsoft.4297127D64EC_8wekyb3d8bbwe"
        for sub in (
            "LocalCache/Roaming/.minecraft",
            "LocalCache/Local/.minecraft",
            "LocalState/.minecraft",
        ):
            root = package / Path(sub)
            candidates += [
                root / "launcher_accounts.json",
                root / "launcher_profiles.json",
                root / "launcher_profiles_microsoft_store.json",
            ]

    seen = set()
    for path in candidates:
        path = Path(path)
        key = str(path).lower()
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        account = _launcher_account_from_json(data)
        if account:
            return account
    return None


def _substitute(value: str, mapping: dict[str, str]) -> str:
    for key, val in mapping.items():
        value = value.replace("${" + key + "}", val)
    return value


def _arg_values(data: dict, mapping: dict[str, str], section: str = "game") -> list[str]:
    args = []
    arguments = data.get("arguments")
    if isinstance(arguments, dict):
        entries = arguments.get(section) or []
        for entry in entries:
            if isinstance(entry, str):
                args.append(_substitute(entry, mapping))
            elif isinstance(entry, dict):
                rules = entry.get("rules") or []
                if _library_allowed({"rules": rules}, features={}):
                    value = entry.get("value")
                    if isinstance(value, list):
                        args.extend(_substitute(str(x), mapping) for x in value)
                    elif isinstance(value, str):
                        args.append(_substitute(value, mapping))
    elif section == "game" and data.get("minecraftArguments"):
        args.extend(_substitute(str(data["minecraftArguments"]), mapping).split())
    return [x for x in args if x != ""]


def _effective_memory(java: str, min_mb: int, max_mb: int) -> tuple[int, int]:
    # Ask the JVM itself whether it's 32-bit rather than guessing from the
    # install path — "Program Files (x86)" is not a reliable signal, since
    # genuinely 64-bit runtimes can live there too, and a false positive
    # here silently clamps the user's configured heap to 1024 MB.
    if is_32bit_jvm(java):
        max_mb = min(int(max_mb), 1024)
        min_mb = min(int(min_mb), max_mb, 512)
    else:
        max_mb = int(max_mb)
        min_mb = min(int(min_mb), max_mb)
    return max(256, min_mb), max(512, max_mb)


def estimate_memory_mb(client_dir: Path, system_total_mb: int | None = None) -> tuple[int, int]:
    """Suggest -Xms/-Xmx for the modpack installed in `client_dir`, sized to
    the pack's mod count/weight rather than a flat default. Never
    recommends more than a safe share of system RAM, so the suggestion
    can't starve the OS/host of memory it needs to keep running.

    Heuristic (not exact — actual needs vary by modpack):
      * Base heap for a modded client: 2048 MB.
      * +24 MB per mod jar beyond the first 10 (more mods == more loaded
        classes/textures/config, roughly tracking mod count).
      * +1 MB per 3 MB of total mod jar size beyond 150 MB (large texture
        packs / resource-heavy mods bloat the atlas beyond what mod count
        alone predicts).
      * Rounded up to the nearest 512 MB, floor 2048 MB, ceiling 8192 MB.
      * Capped at 50% of system RAM (or 75% if system RAM is >= 16 GB) so
        the suggestion leaves room for the OS, launcher, and everything
        else running — i.e. it won't recommend "drain all of it".
    """
    mods_dir = client_dir / "mods"
    jar_count = 0
    total_bytes = 0
    if mods_dir.is_dir():
        for f in mods_dir.iterdir():
            if f.is_file() and f.suffix.lower() == ".jar":
                jar_count += 1
                try:
                    total_bytes += f.stat().st_size
                except OSError:
                    pass
    total_mb = total_bytes / (1024 * 1024)

    max_mb = 2048.0
    max_mb += max(0, jar_count - 10) * 24
    max_mb += max(0.0, total_mb - 150) / 3
    max_mb = int(round(max_mb / 512) * 512)
    max_mb = max(2048, min(8192, max_mb))

    if system_total_mb is None:
        try:
            import psutil
            system_total_mb = int(psutil.virtual_memory().total / (1024 * 1024))
        except Exception:
            system_total_mb = None

    if system_total_mb:
        share = 0.75 if system_total_mb >= 16384 else 0.5
        cap = int(round((system_total_mb * share) / 512) * 512)
        max_mb = max(2048, min(max_mb, cap))

    min_mb = max(1024, max_mb // 2)
    min_mb = int(round(min_mb / 512) * 512)
    return min_mb, max_mb


def launch_minecraft_direct(client_dir: Path, version_id: str, java_path: str,
                            min_mb: int = 1024, max_mb: int = 4096) -> tuple[int, int, subprocess.Popen]:
    """Start the prepared client directly using the manager's Microsoft session.
    Returns (min_mb, max_mb, proc) - the memory actually applied after
    `_effective_memory` clamping, plus the live Popen handle so the caller
    can stream the game's stdout/stderr into its own console instead of
    letting it fall through to whatever terminal launched the manager."""
    account = _get_account()
    if not account:
        raise RuntimeError(
            "No Minecraft account is connected to Game Server Manager. "
            "Use Modpacks → Sign in with Microsoft first."
        )

    mc_dir = minecraft_dir()
    data, _ = _version_json(mc_dir, version_id)
    version_dir = mc_dir / "versions" / version_id
    # Modern Forge/NeoForge version metadata has no "jar" field (only old
    # Forge 1.12.x sets one), so without the "inherits" fallback this would
    # resolve to the loader's own id (e.g. "1.16.5-forge-36.2.34") and look
    # for a client jar that's never produced under that folder — the real
    # jar lives under the vanilla version's own directory.
    jar_name = str(data.get("jar") or data.get("inherits") or version_id)
    client_jar = mc_dir / "versions" / jar_name / f"{jar_name}.jar"
    if not client_jar.exists():
        # Forge 1.12.x normally inherits the vanilla jar.
        _ensure_vanilla_version(mc_dir, str(data.get("inherits") or data.get("id") or jar_name))
        if not client_jar.exists():
            raise RuntimeError(f"Minecraft client JAR is missing: {client_jar}")

    assets = data.get("assets") or data.get("assetIndex", {}).get("id") or ""
    asset_root = mc_dir / "assets"
    natives_dir = client_dir / "natives"
    natives_dir.mkdir(parents=True, exist_ok=True)
    libs = _ensure_libraries(mc_dir, data.get("libraries") or [], natives_dir)
    # Modern NeoForge/Forge (1.20.5+) resolve and SRG-remap their own client
    # jar at runtime via a "production client provider" library entry
    # already present in data["libraries"] (name ending in ":client") - it's
    # already in `libs` at this point. Unconditionally appending the raw
    # vanilla client_jar on top of that put two jars containing the same
    # net.minecraft.data package on the module path, which is a hard
    # ResolutionException ("module X contains package Y, module Z exports
    # package Y") before the game window even opens. Only append the plain
    # vanilla jar when the loader hasn't already supplied its own client
    # artifact (legacy Forge, or truly vanilla launches).
    has_own_client_artifact = any(
        str((lib or {}).get("name") or "").endswith(":client")
        for lib in (data.get("libraries") or [])
        if isinstance(lib, dict)
    )
    if not has_own_client_artifact:
        libs.append(client_jar)

    min_mb, max_mb = _effective_memory(java_path, min_mb, max_mb)
    verified_max, probe_notes = max_settable_heap_mb(java_path, max_mb)
    if verified_max != max_mb:
        max_mb = verified_max
        min_mb = min(min_mb, max_mb)
    global _last_heap_probe_notes
    _last_heap_probe_notes = probe_notes
    access_token = account["accessToken"]
    cp_sep = ";" if platform.system() == "Windows" else ":"
    mapping = {
        "auth_player_name": account["name"],
        "auth_uuid": account["uuid"],
        "auth_access_token": access_token,
        "user_type": account.get("userType", "msa"),
        "user_properties": "{}",
        "version_name": version_id,
        "version_type": "release",
        "game_directory": str(client_dir),
        "assets_root": str(asset_root),
        "assets_index_name": str(assets),
        "auth_xuid": "",
        "clientid": "",
        "natives_directory": str(natives_dir),
        "launcher_name": "Game Server Manager",
        "launcher_version": "1.0",
        "classpath": "",
        "classpath_separator": cp_sep,
        "library_directory": str(mc_dir / "libraries"),
    }
    jvm_args = _arg_values(data, mapping, "jvm")
    game_args = _arg_values(data, mapping, "game")

    main_class = str(data.get("mainClass") or "")
    if not main_class:
        raise RuntimeError(f"No main class is defined for {version_id}.")

    classpath = cp_sep.join(str(p) for p in libs if p.exists())
    if not classpath:
        raise RuntimeError("No Minecraft libraries were found for the client.")

    # Modern NeoForge/Fabric/Quilt metadata puts required flags in
    # arguments.jvm. Forge 1.12.x generally has no JVM argument section.
    # Some loader/modpack metadata sneaks its own -Xms/-Xmx in here (e.g.
    # via a "javaArguments" style entry carried over from an installer
    # profile) — if that string comes after ours, Java honors *that* one
    # and silently falls back to its own default heap sizing, which is
    # exactly the "989 MB out of nowhere" symptom. Strip any such tokens
    # so our explicit -Xms/-Xmx below are always the ones that win.
    jvm_args = [
        x for x in jvm_args
        if x not in {"${classpath}", "-cp", "${classpath}"} and x != classpath
        and not re.match(r"^-Xm[sx]", str(x), re.IGNORECASE)
    ]
    jvm_args = [_substitute(x, {"${classpath}": classpath}) for x in jvm_args]
    cmd = [
        str(java_path), f"-Xms{min_mb}M", f"-Xmx{max_mb}M",
        f"-Djava.library.path={natives_dir}",
        *jvm_args,
        "-cp", classpath, main_class, *game_args,
    ]
    # Forge 1.12.2's Launchwrapper uses the working directory as gameDir.
    client_dir.mkdir(parents=True, exist_ok=True)
    # Pipe stdout/stderr instead of inheriting them - without this the
    # game's entire log (including whatever it prints right before a
    # crash) went straight to the terminal the manager happened to be
    # launched from, invisible to anyone running the manager as a GUI
    # app. Capturing it here lets the caller stream it into the
    # manager's own console the same way a normal server's output is.
    popen_kwargs: dict = dict(
        cwd=str(client_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        close_fds=True,
    )
    if platform.system() == "Windows":
        popen_kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.Popen(cmd, **popen_kwargs)
    return min_mb, max_mb, proc



def _install_client_installer(java_path: str, installer: Path, mc_dir: Path, *extra_args: str) -> None:
    """Run a mod-loader client installer into the shared .minecraft directory."""
    proc = subprocess.run(
        [java_path, "-jar", str(installer), *extra_args, str(mc_dir)],
        cwd=str(mc_dir), capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(
            f"Client loader installation failed (code {proc.returncode}). {detail[-1600:]}"
        )


def _download_neoforge_client(mc_dir: Path, mc_version: str, loader_version: str, java_path: str) -> str:
    installer_url = (
        "https://maven.neoforged.net/releases/net/neoforged/neoforge/"
        f"{loader_version}/neoforge-{loader_version}-installer.jar"
    )
    with tempfile.TemporaryDirectory(prefix="gsm_neoforge_client_") as td:
        installer = Path(td) / "neoforge-installer.jar"
        _download(installer_url, installer)
        proc = subprocess.run(
            [java_path, "-jar", str(installer), "--install-client"],
            cwd=str(mc_dir), capture_output=True, text=True, timeout=600,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(
                f"NeoForge client installation failed (code {proc.returncode}). {detail[-1600:]}"
            )
    preferred = mc_dir / "versions" / f"neoforge-{loader_version}" / f"neoforge-{loader_version}.json"
    if preferred.exists():
        return f"neoforge-{loader_version}"

    # Some NeoForge installer builds use a slightly different version id.
    # Prefer a version metadata file that actually references the requested
    # loader instead of blindly selecting the newest NeoForge installation.
    matches = []
    for p in (mc_dir / "versions").glob("neoforge-*/neoforge-*.json"):
        try:
            info = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(info.get("id") or p.stem) == f"neoforge-{loader_version}":
            return p.parent.name
        if loader_version in p.parent.name:
            matches.append(p.parent.name)
    if matches:
        return sorted(matches, reverse=True)[0]

    raise RuntimeError(
        f"NeoForge {loader_version} installed, but no client version metadata was created. "
        "The NeoForge installer may require a compatible Java runtime."
    )


def _fabric_installer_version() -> str:
    data = requests.get("https://meta.fabricmc.net/v2/versions/installer", headers={"User-Agent": UA}, timeout=30)
    data.raise_for_status()
    for item in data.json():
        if isinstance(item, dict) and item.get("stable") and item.get("version"):
            return str(item["version"])
    raise RuntimeError("Could not determine a stable Fabric installer version.")


def _install_fabric_client(mc_dir: Path, mc_version: str, loader_version: str, java_path: str) -> str:
    installer_version = _fabric_installer_version()
    url = (
        f"https://maven.fabricmc.net/net/fabricmc/fabric-installer/"
        f"{installer_version}/fabric-installer-{installer_version}.jar"
    )
    with tempfile.TemporaryDirectory(prefix="gsm_fabric_client_") as td:
        installer = Path(td) / "fabric-installer.jar"
        _download(url, installer)
        proc = subprocess.run(
            [
                java_path, "-jar", str(installer),
                "client", "-mcversion", mc_version,
                "-loader", loader_version, "-dir", str(mc_dir), "-noprofile"
            ],
            cwd=str(mc_dir), capture_output=True, text=True, timeout=600,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"Fabric client installation failed (code {proc.returncode}). {detail[-1600:]}")
    version_id = f"fabric-loader-{loader_version}-{mc_version}"
    if not (mc_dir / "versions" / version_id / f"{version_id}.json").exists():
        raise RuntimeError(f"Fabric client installation completed, but {version_id} was not created.")
    return version_id


def _quilt_installer_version() -> str:
    data = requests.get("https://meta.quiltmc.org/v3/versions/installer", headers={"User-Agent": UA}, timeout=30)
    data.raise_for_status()
    for item in data.json():
        if isinstance(item, dict) and item.get("version"):
            return str(item["version"])
    raise RuntimeError("Could not determine a Quilt installer version.")


def _install_quilt_client(mc_dir: Path, mc_version: str, loader_version: str, java_path: str) -> str:
    installer_version = _quilt_installer_version()
    url = (
        f"https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/"
        f"{installer_version}/quilt-installer-{installer_version}.jar"
    )
    with tempfile.TemporaryDirectory(prefix="gsm_quilt_client_") as td:
        installer = Path(td) / "quilt-installer.jar"
        _download(url, installer)
        proc = subprocess.run(
            [
                java_path, "-jar", str(installer),
                "install", "client", mc_version, loader_version,
                "--dir", str(mc_dir), "--no-profile"
            ],
            cwd=str(mc_dir), capture_output=True, text=True, timeout=600,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"Quilt client installation failed (code {proc.returncode}). {detail[-1600:]}")
    version_id = f"quilt-loader-{loader_version}-{mc_version}"
    if not (mc_dir / "versions" / version_id / f"{version_id}.json").exists():
        # Some Quilt installer releases use a slightly different version id.
        matches = sorted(
            (p.parent.name for p in (mc_dir / "versions").glob(f"quilt-loader-*{mc_version}*/quilt-loader-*.json")),
            reverse=True,
        )
        if matches:
            return matches[0]
        raise RuntimeError(f"Quilt client installation completed, but no client version metadata was created.")
    return version_id


def prepare_client(
    server_dir: Path,
    mc_version: str,
    loader: str,
    loader_version: str,
    java_path: str,
    profile_name: str,
    instance_id: str,
    *,
    curseforge_api_key: str = "",
    project_id: int = 0,
    file_id: int = 0,
) -> tuple[Path, str]:
    """Prepare a direct-launch client for a modpack.

    Covers Forge, NeoForge, Fabric, and Quilt modloader packs, as well as
    "vanilla" modpacks — packs whose manifest has no modLoaders entry
    (resource packs, data packs, configs, world files only). CurseForge's
    own launcher treats those as ordinary modpacks and just runs the plain
    Minecraft version with the pack's overrides applied; this does the same
    instead of refusing to prepare a client for them.
    """
    loader = str(loader or "").lower().strip()
    if not loader:
        loader = "vanilla"
    if loader == "forge":
        return prepare_forge_client(
            server_dir, mc_version, loader_version, java_path, profile_name, instance_id,
            curseforge_api_key=curseforge_api_key, project_id=project_id, file_id=file_id,
        )

    if loader not in {"neoforge", "fabric", "quilt", "vanilla"}:
        raise RuntimeError(f"Unsupported client modloader: {loader or 'unknown'}")
    if not mc_version:
        raise RuntimeError("The modpack is missing its Minecraft version.")
    if loader != "vanilla" and not loader_version:
        raise RuntimeError("The modpack is missing its loader version.")

    mc_dir = minecraft_dir()
    mc_dir.mkdir(parents=True, exist_ok=True)
    _ensure_vanilla_version(mc_dir, mc_version)

    if loader == "neoforge":
        version_id = _download_neoforge_client(mc_dir, mc_version, loader_version, java_path)
    elif loader == "fabric":
        version_id = _install_fabric_client(mc_dir, mc_version, loader_version, java_path)
    elif loader == "quilt":
        version_id = _install_quilt_client(mc_dir, mc_version, loader_version, java_path)
    else:
        # Vanilla modpack: no loader install needed, just the plain version.
        version_id = mc_version

    client_dir = mc_dir / "game-server-manager" / instance_id
    client_dir.mkdir(parents=True, exist_ok=True)

    if curseforge_api_key and project_id and not _server_mods_populated(server_dir):
        if file_id and _modpack_already_installed(client_dir, project_id, file_id):
            resolved_file_id = file_id
        else:
            client_file = _find_client_file(curseforge_api_key, project_id, mc_version, file_id)
            resolved_file_id = int(client_file["id"])
            if not _modpack_already_installed(client_dir, project_id, resolved_file_id):
                client_url = _cf_download_url(curseforge_api_key, project_id, resolved_file_id)
                with tempfile.TemporaryDirectory(prefix="gsm_client_pack_") as td:
                    archive = Path(td) / "client-pack.zip"
                    req = requests.get(client_url, headers={"User-Agent": UA}, timeout=120)
                    req.raise_for_status()
                    archive.write_bytes(req.content)
                    root = Path(td) / "root"
                    root.mkdir()
                    with zipfile.ZipFile(archive) as zf:
                        zf.extractall(root)
                    manifest_path = root / "manifest.json"
                    if not manifest_path.exists():
                        matches = list(root.glob("*/manifest.json"))
                        if matches:
                            manifest_path = matches[0]
                    try:
                        if manifest_path.exists():
                            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                            _install_client_manifest(manifest_path.parent, manifest, client_dir, curseforge_api_key)
                        else:
                            _copy_client_files(root, client_dir)
                    finally:
                        # Mark done even on partial failure (e.g. mods the author
                        # blocked from third-party download) - those will never
                        # succeed on retry, so re-attempting on every launch would
                        # just re-fail forever instead of letting the user launch
                        # once they've added the missing files manually.
                        _mark_modpack_installed(client_dir, project_id, resolved_file_id)
    else:
        # No CurseForge fetch needed/possible: either there's no project_id
        # to look up, or the server's mods folder is already populated
        # (manually copied in, or already downloaded by a prior server
        # install) — just mirror those files straight into the client.
        _copy_client_files(server_dir, client_dir)

    _write_profile(mc_dir, f"gsm-{instance_id}", profile_name, version_id, client_dir)
    return client_dir, version_id


def prepare_forge_client(
    server_dir: Path,
    mc_version: str,
    forge_version: str,
    java_path: str,
    profile_name: str,
    instance_id: str,
    *,
    curseforge_api_key: str = "",
    project_id: int = 0,
    file_id: int = 0,
) -> tuple[Path, str]:
    if not mc_version:
        raise RuntimeError("The installed modpack has no Minecraft version.")
    if not forge_version:
        raise RuntimeError("The installed modpack has no Forge version to install on the client.")

    mc_dir = minecraft_dir()
    mc_dir.mkdir(parents=True, exist_ok=True)
    version_id = f"{mc_version}-forge-{forge_version}"
    version_dir = mc_dir / "versions" / version_id
    version_json = version_dir / f"{version_id}.json"

    if not version_json.exists():
        url = (
            "https://maven.minecraftforge.net/net/minecraftforge/forge/"
            f"{mc_version}-{forge_version}/forge-{mc_version}-{forge_version}-installer.jar"
        )
        with tempfile.TemporaryDirectory(prefix="gsm_forge_client_") as td:
            installer = Path(td) / "forge-installer.jar"
            _download(url, installer)
            _run_installer(java_path, installer, mc_dir)

    # Ensure the vanilla parent/client/assets exist even if the Forge installer
    # did not need to download them.
    _ensure_vanilla_version(mc_dir, mc_version)

    client_dir = mc_dir / "game-server-manager" / instance_id
    client_dir.mkdir(parents=True, exist_ok=True)

    if curseforge_api_key and project_id and not _server_mods_populated(server_dir):
        if file_id and _modpack_already_installed(client_dir, project_id, file_id):
            resolved_file_id = file_id
        else:
            client_file = _find_client_file(curseforge_api_key, project_id, mc_version, file_id)
            resolved_file_id = int(client_file["id"])
            if not _modpack_already_installed(client_dir, project_id, resolved_file_id):
                client_url = _cf_download_url(curseforge_api_key, project_id, resolved_file_id)
                with tempfile.TemporaryDirectory(prefix="gsm_client_pack_") as td:
                    archive = Path(td) / "client-pack.zip"
                    req = requests.get(client_url, headers={"User-Agent": UA}, timeout=120)
                    req.raise_for_status()
                    archive.write_bytes(req.content)
                    root = Path(td) / "root"
                    root.mkdir()
                    with zipfile.ZipFile(archive) as zf:
                        zf.extractall(root)
                    manifest_path = root / "manifest.json"
                    if not manifest_path.exists():
                        matches = list(root.glob("*/manifest.json"))
                        if matches:
                            manifest_path = matches[0]
                    try:
                        if manifest_path.exists():
                            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                            _install_client_manifest(manifest_path.parent, manifest, client_dir, curseforge_api_key)
                        else:
                            _copy_client_files(root, client_dir)
                    finally:
                        _mark_modpack_installed(client_dir, project_id, resolved_file_id)
    else:
        _copy_client_files(server_dir, client_dir)

    _write_profile(mc_dir, f"gsm-{instance_id}", profile_name, version_id, client_dir)
    return client_dir, version_id


def open_minecraft_launcher() -> None:
    launcher = find_launcher()
    if launcher:
        subprocess.Popen([str(launcher)], close_fds=True)
        return
    if platform.system() == "Windows":
        for app_id in (
            "Microsoft.4297127D64EC_8wekyb3d8bbwe!Minecraft",
            "Microsoft.4297127D64EC_8wekyb3d8bbwe!MinecraftLauncher",
        ):
            try:
                subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"], close_fds=True)
                return
            except Exception:
                pass
        raise RuntimeError("Minecraft Launcher was not found. Install the official Minecraft Launcher first.")
    raise RuntimeError("Minecraft Launcher was not found. Install the official Minecraft Launcher first.")