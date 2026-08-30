"""Minecraft Java loader metadata, installation and launch helpers."""
from __future__ import annotations

import platform
import re
import queue
import subprocess
import json
import zipfile
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from ..core.events import DownloadEvent
from .java_runtimes import is_32bit_jvm, max_settable_heap_mb

_last_heap_probe_notes: list[str] = []


def get_last_heap_probe_notes() -> list[str]:
    return list(_last_heap_probe_notes)

UA = "ZsMultiTool-GameServerManager/1.0"
FORGE_PROMOTIONS_URL = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
NEOFORGE_METADATA_URL = "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
FABRIC_META = "https://meta.fabricmc.net"
QUILT_META = "https://meta.quiltmc.org/v3"

LOADER_NAMES = {
    "vanilla": "Vanilla",
    "forge": "Forge",
    "neoforge": "NeoForge",
    "fabric": "Fabric",
    "quilt": "Quilt",
}

@dataclass(frozen=True)
class LoaderVersion:
    id: str
    label: str
    loader: str


def loader_choices() -> list[str]:
    return list(LOADER_NAMES)


def loader_name(loader: str) -> str:
    return LOADER_NAMES.get(loader, loader.title())


def _get_json(url: str) -> Any:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.json()


def _get_text(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.text


def _mc_key(version: str) -> str:
    return version.strip()


def get_loader_versions(loader: str, minecraft_version: str) -> tuple[list[LoaderVersion], str]:
    """Return versions compatible with the selected Minecraft version."""
    if not minecraft_version:
        return [], "Select a Minecraft version first."
    try:
        if loader == "vanilla":
            return [LoaderVersion("", "Vanilla", loader)], ""
        if loader == "forge":
            data = _get_json(FORGE_PROMOTIONS_URL)
            promos = data.get("promos", {}) if isinstance(data, dict) else {}
            prefix = f"{_mc_key(minecraft_version)}-"
            vals = []
            for key, value in promos.items():
                if key.startswith(prefix) and value:
                    suffix = key[len(prefix):]
                    if suffix in {"recommended", "latest"}:
                        vals.append((0 if suffix == "recommended" else 1, str(value), suffix))
            vals.sort(key=lambda x: (x[0], x[1]), reverse=False)
            # Prefer recommended, then latest; avoid duplicates.
            out=[]; seen=set()
            for _, v, label in vals:
                if v not in seen:
                    seen.add(v); out.append(LoaderVersion(v, f"{v} ({label})", loader))
            return out, ""
        if loader == "fabric":
            data = _get_json(f"{FABRIC_META}/v2/versions/loader/{minecraft_version}")
            out=[]
            for item in data:
                v = str(item.get("loader", {}).get("version", ""))
                if v: out.append(LoaderVersion(v, v, loader))
            return out, ""
        if loader == "quilt":
            data = _get_json(f"{QUILT_META}/versions/loader/{minecraft_version}")
            out=[]
            for item in data:
                v = str(item.get("version", ""))
                if v: out.append(LoaderVersion(v, v, loader))
            return out, ""
        if loader == "neoforge":
            # NeoForge Maven versions encode the supported MC line as 20.4, 21.1, 21.8, etc.
            parts = minecraft_version.split(".")
            prefix = (parts[1] + "." + parts[2]) if len(parts) >= 3 else minecraft_version
            data = _get_text(NEOFORGE_METADATA_URL)
            root = ET.fromstring(data)
            versions = [e.text.strip() for e in root.findall(".//version") if e.text and e.text.strip()]
            compatible = [v for v in versions if v.startswith(prefix + ".") or v.startswith(prefix + "-")]
            compatible = list(dict.fromkeys(reversed(compatible)))
            return [LoaderVersion(v, v, loader) for v in compatible], ""
        return [], f"Unsupported Minecraft loader: {loader}"
    except Exception as exc:
        return [], f"Couldn't load {loader_name(loader)} versions: {exc}"


def _download(url: str, dest: Path, events: queue.Queue | None = None, message: str = "Downloading…") -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, headers={"User-Agent": UA}, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(256 * 1024):
                if not chunk: continue
                f.write(chunk); done += len(chunk)
                if events is not None:
                    events.put(DownloadEvent(kind="progress", downloaded=done, total=total, message=message if not total else ""))
    tmp.replace(dest)


def _run_installer(java: str, installer: Path, server_dir: Path, events: queue.Queue) -> None:
    events.put(DownloadEvent(kind="progress", downloaded=50, total=100, message="Running server installer…"))
    proc = subprocess.run([java, "-jar", str(installer), "--installServer"], cwd=str(server_dir), capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "installer failed").strip()
        raise RuntimeError(detail[-2000:])


def _effective_memory(java: str, min_mb: int, max_mb: int) -> tuple[int, int]:
    """Return safe heap values for the selected JVM.

    Legacy Minecraft 1.12.2/Forge often uses Java 8, and a 32-bit JVM cannot
    reserve a 2 GB heap reliably. Cap it below the 32-bit address-space limit
    instead of allowing the server to fail before Forge starts.

    Bitness is asked of the JVM itself (see is_32bit_jvm) rather than
    guessed from the install path — "Program Files (x86)" isn't a reliable
    signal, since genuinely 64-bit runtimes can live there too, and a false
    positive here used to silently clamp the configured heap to 1024 MB.
    """
    if is_32bit_jvm(java):
        # 1024 MB is conservative enough for a 32-bit Java 8 process while
        # leaving address space for Forge, native libraries and the OS.
        max_mb = min(int(max_mb), 1024)
        min_mb = min(int(min_mb), max_mb, 512)
    else:
        max_mb = int(max_mb)
        min_mb = min(int(min_mb), max_mb)
    return max(256, min_mb), max(512, max_mb)


def _set_memory(server_dir: Path, min_mb: int, max_mb: int) -> None:
    """Best-effort JVM heap override for installer-generated user_jvm_args.txt."""
    path = server_dir / "user_jvm_args.txt"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"(?m)^\s*-Xms\S+\s*$\n?", "", text)
    text = re.sub(r"(?m)^\s*-Xmx\S+\s*$\n?", "", text)
    text.rstrip()
    text += f"\n-Xms{min_mb}M\n-Xmx{max_mb}M\n"
    path.write_text(text, encoding="utf-8")


def launch_command(server_dir: Path, config: dict) -> list[str]:
    loader = str(config.get("loader", "vanilla")).lower()
    java = str(config.get("java_path", "java"))
    min_mb = int(config.get("min_mb", 1024))
    max_mb = int(config.get("max_mb", 2048))
    min_mb, max_mb = _effective_memory(java, min_mb, max_mb)
    verified_max, probe_notes = max_settable_heap_mb(java, max_mb)
    if verified_max != max_mb:
        max_mb = verified_max
        min_mb = min(min_mb, max_mb)
    global _last_heap_probe_notes
    _last_heap_probe_notes = probe_notes
    extra = str(config.get("extra_args", "")).split()
    if loader == "vanilla":
        return [java, f"-Xms{min_mb}M", f"-Xmx{max_mb}M", *extra, "-jar", "server.jar", "nogui"]
    if loader == "fabric":
        jar = next(iter(sorted(server_dir.glob("fabric-server-launch*.jar"))), server_dir / "fabric-server-launch.jar")
        return [java, f"-Xms{min_mb}M", f"-Xmx{max_mb}M", *extra, "-jar", jar.name, "nogui"]
    if loader == "quilt":
        jar = next(iter(sorted(server_dir.glob("quilt-server-launch*.jar"))), server_dir / "quilt-server-launch.jar")
        return [java, f"-Xms{min_mb}M", f"-Xmx{max_mb}M", *extra, "-jar", jar.name, "nogui"]
    script = "run.bat" if platform.system() == "Windows" else "run.sh"
    script_path = server_dir / script
    if not script_path.exists():
        if loader == "forge":
            legacy = sorted(
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
            if legacy:
                return [java, f"-Xms{min_mb}M", f"-Xmx{max_mb}M", *extra, "-jar", legacy[0].name, "nogui"]
        raise FileNotFoundError(f"{script} wasn't found for {loader_name(loader)}.")
    if platform.system() == "Windows":
        return ["cmd", "/c", script]
    return [str(script_path)]


def launcher_markers(server_dir: Path, loader: str) -> list[Path]:
    if loader == "vanilla":
        return [server_dir / "server.jar"]
    if loader == "forge":
        # Modern Forge uses run.bat/run.sh; legacy Forge (1.12.x and similar)
        # may only have a generated forge-*.jar.
        return [
            server_dir / "run.bat",
            server_dir / "run.sh",
            *sorted(
                [
                    p for p in server_dir.glob("forge-*.jar")
                    if p.is_file()
                    and "installer" not in p.name.lower()
                    and "sources" not in p.name.lower()
                    and "changelog" not in p.name.lower()
                ],
                key=lambda p: p.stat().st_mtime if p.exists() else 0,
                reverse=True,
            ),
        ]
    if loader == "neoforge":
        return [server_dir / "run.bat", server_dir / "run.sh"]
    if loader == "fabric": return [p for p in server_dir.glob("fabric-server-launch*.jar")]
    if loader == "quilt": return [p for p in server_dir.glob("quilt-server-launch*.jar")]
    return []


def detect_loader(server_dir: Path) -> str | None:
    if (server_dir / "server.jar").exists() and not (server_dir / "run.bat").exists() and not list(server_dir.glob("*server-launch*.jar")):
        return "vanilla"
    if (server_dir / "run.bat").exists() or (server_dir / "run.sh").exists():
        if (server_dir / "libraries" / "net" / "neoforged").exists(): return "neoforge"
        if (server_dir / "libraries" / "net" / "minecraftforge").exists(): return "forge"
    if any(
        p.is_file()
        and "installer" not in p.name.lower()
        and "sources" not in p.name.lower()
        and "changelog" not in p.name.lower()
        for p in server_dir.glob("forge-*.jar")
    ): return "forge"
    if list(server_dir.glob("fabric-server-launch*.jar")): return "fabric"
    if list(server_dir.glob("quilt-server-launch*.jar")): return "quilt"
    return None



def detect_minecraft_version(server_dir: Path) -> str | None:
    """Best-effort detection of the Minecraft version actually present in a server folder.

    Logs are preferred because Vanilla/Forge/NeoForge/Fabric/Quilt all normally emit
    the Minecraft version during startup.  A few jar metadata layouts are also checked
    as a fallback.
    """
    log_candidates = [server_dir / "logs" / "latest.log"]
    log_candidates.extend(sorted((server_dir / "logs").glob("*.log"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True) if (server_dir / "logs").exists() else [])
    patterns = (
        re.compile(r"Starting minecraft server version\s+([^\s]+)", re.IGNORECASE),
        re.compile(r"Minecraft version\s*[:=]\s*([0-9]+(?:\.[0-9]+)+(?:[-+][A-Za-z0-9._-]+)?)", re.IGNORECASE),
    )
    seen = set()
    for path in log_candidates:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pattern in patterns:
            matches = list(pattern.finditer(text))
            if matches:
                return matches[-1].group(1).strip()

    # Vanilla server jars have used version metadata in different places across releases.
    jars = []
    for name in ("server.jar",):
        candidate = server_dir / name
        if candidate.is_file():
            jars.append(candidate)
    jars.extend(sorted(server_dir.glob("*-server-launch*.jar"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True))
    for jar in jars:
        try:
            with zipfile.ZipFile(jar) as zf:
                for name in ("version.json", "META-INF/version.json"):
                    if name not in zf.namelist():
                        continue
                    data = json.loads(zf.read(name).decode("utf-8", errors="replace"))
                    if isinstance(data, dict):
                        for key in ("id", "name", "version"):
                            value = data.get(key)
                            if isinstance(value, str) and re.fullmatch(r"[0-9]+(?:\.[0-9]+)+(?:[-+][A-Za-z0-9._-]+)?", value):
                                return value
                manifest_name = "META-INF/MANIFEST.MF"
                if manifest_name in zf.namelist():
                    manifest = zf.read(manifest_name).decode("utf-8", errors="replace")
                    m = re.search(r"(?:Implementation-Version|Specification-Version):\s*([^\r\n]+)", manifest, re.IGNORECASE)
                    if m and re.fullmatch(r"[0-9]+(?:\.[0-9]+)+(?:[-+][A-Za-z0-9._-]+)?", m.group(1).strip()):
                        return m.group(1).strip()
        except (OSError, zipfile.BadZipFile, ValueError, json.JSONDecodeError):
            continue
    return None

def create_install_worker(server_dir: Path, loader: str, minecraft_version: str, loader_version: str,
                          java_path: str = "java", min_mb: int = 1024, max_mb: int = 2048) -> threading.Thread:
    class Worker(threading.Thread):
        def __init__(self):
            super().__init__(daemon=True); self.events = __import__("queue").Queue(); self.version = minecraft_version
        def run(self):
            try:
                server_dir.mkdir(parents=True, exist_ok=True)
                if loader == "vanilla":
                    from .. import backend as mc
                    versions, error = mc.list_versions()
                    if error:
                        raise RuntimeError(error)
                    selected = next((v for v in versions if v.id == minecraft_version), None)
                    if selected is None:
                        raise RuntimeError(f"Minecraft version {minecraft_version} was not found in Mojang's manifest.")
                    info, error = mc.get_server_download_info(selected)
                    if error or info is None:
                        raise RuntimeError(error or "No Vanilla download information.")
                    worker = mc.ServerDownloadWorker(info, server_dir)
                    worker.events = self.events
                    worker.run()
                    return
                if loader == "fabric":
                    installers = _get_json(f"{FABRIC_META}/v2/versions/installer")
                    installer_version = next((str(x.get("version")) for x in installers if x.get("stable")), str(installers[0].get("version")))
                    url = f"{FABRIC_META}/v2/versions/loader/{minecraft_version}/{loader_version}/{installer_version}/server/jar"
                    dest = server_dir / f"fabric-server-mc.{minecraft_version}-loader.{loader_version}-launcher.{installer_version}.jar"
                    _download(url, dest, self.events)
                    self.events.put(DownloadEvent(kind="done", message="Fabric server launcher installed.")); return
                if loader == "quilt":
                    url = f"{QUILT_META}/versions/loader/{minecraft_version}/{loader_version}/server/jar"
                    dest = server_dir / f"quilt-server-launcher.{loader_version}.jar"
                    _download(url, dest, self.events)
                    self.events.put(DownloadEvent(kind="done", message="Quilt server launcher installed.")); return
                if loader == "forge":
                    installer = server_dir / f"forge-{minecraft_version}-{loader_version}-installer.jar"
                    url = f"https://maven.minecraftforge.net/net/minecraftforge/forge/{minecraft_version}-{loader_version}/forge-{minecraft_version}-{loader_version}-installer.jar"
                elif loader == "neoforge":
                    installer = server_dir / f"neoforge-{loader_version}-installer.jar"
                    url = f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{loader_version}/neoforge-{loader_version}-installer.jar"
                else:
                    raise RuntimeError(f"Unsupported loader: {loader}")
                _download(url, installer, self.events, f"Downloading {loader_name(loader)} installer…")
                _run_installer(java_path, installer, server_dir, self.events)
                installer.unlink(missing_ok=True)
                _set_memory(server_dir, min_mb, max_mb)
                self.events.put(DownloadEvent(kind="done", message=f"{loader_name(loader)} server installed."))
            except Exception as exc:
                self.events.put(DownloadEvent(kind="error", message=str(exc)))
    return Worker()
