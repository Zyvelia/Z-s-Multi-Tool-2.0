"""
Minecraft Server Manager — core logic.

Supports both Minecraft editions:
  - Java Edition: talks to Mojang's official, public metadata API —
    the same one the real Minecraft Launcher uses — to list versions
    and get a verified (SHA1-checked) server.jar download URL, then
    runs it as a local `java -jar server.jar nogui` process.
  - Bedrock Edition: talks to Mojang's Bedrock Dedicated Server
    download-links API (the same one minecraft.net's own download
    page uses) to get the latest server build for this platform, then
    runs the native `bedrock_server` binary directly — no JVM needed.

Both server processes are run headless with their stdin/stdout piped
so this module can render its own console UI instead of a native
window, and send commands to them.

Legal note: Mojang's EULA (https://aka.ms/MinecraftEULA) must be
accepted to run a server. This module never writes `eula=true` (Java)
or records EULA acknowledgement (Bedrock) without the user explicitly
checking an "I agree" box in the UI first — see write_eula() and
write_bedrock_eula_ack() below.
"""

from __future__ import annotations

import hashlib
import json
import platform
import queue
import re
import subprocess
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import requests

try:
    # Project convention: user-data lives under %APPDATA%\ZsMultiTool\
    # via core/paths.py. Falling back below keeps this module usable
    # standalone (e.g. outside the full app, or during testing).
    from core import paths  # type: ignore

    def _settings_file() -> Path:
        return Path(paths.data_path("minecraft_server", "settings.json"))
except ImportError:  # pragma: no cover - fallback for standalone use/testing
    def _settings_file() -> Path:
        import os
        base = Path(os.environ.get("APPDATA", Path.home())) / "ZsMultiTool" / "minecraft_server"
        base.mkdir(parents=True, exist_ok=True)
        return base / "settings.json"

_CREATE_NO_WINDOW = 0x08000000
VERSION_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
EULA_URL = "https://aka.ms/MinecraftEULA"

# Same download-links API minecraft.net's own Bedrock download page calls.
BEDROCK_LINKS_URL = "https://net-secondary.web.minecraft-services.net/api/v1.0/download/links"
# Mojang's CDN blocks requests with obviously-scripted user agents, so we
# identify as a normal browser for both the API call and the zip download.
_BEDROCK_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


# =====================================================================
# SETTINGS (last-used folder, version, memory, java path)
# =====================================================================

def load_settings() -> dict:
    f = _settings_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_settings(data: dict) -> None:
    try:
        _settings_file().write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


# =====================================================================
# JAVA DETECTION
# =====================================================================

def check_java(java_path: str = "java") -> tuple[bool, str]:
    """Returns (found, version_string)."""
    try:
        proc = subprocess.run(
            [java_path, "-version"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=_CREATE_NO_WINDOW, timeout=10,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False, ""
    output = (proc.stderr or "") + (proc.stdout or "")
    m = re.search(r'version "([^"]+)"', output)
    if m:
        return True, m.group(1)
    first_line = output.strip().splitlines()[0] if output.strip() else ""
    return bool(first_line), first_line


# =====================================================================
# TAILSCALE IP DETECTION
# =====================================================================

TAILSCALE_CANDIDATES = [
    "tailscale",
    r"C:\Program Files\Tailscale\tailscale.exe",
    r"C:\Program Files (x86)\Tailscale\tailscale.exe",
]


def get_tailscale_ip() -> tuple[str, str]:
    """Returns (ip, error). Tries the `tailscale` CLI (PATH first, then
    the default Windows install locations, since the GUI installer
    doesn't always put it on PATH) and asks it for this machine's
    Tailscale IPv4 address — the address other devices on the tailnet
    would use to reach this server."""
    last_error = "Tailscale CLI not found."
    for exe in TAILSCALE_CANDIDATES:
        try:
            proc = subprocess.run(
                [exe, "ip", "-4"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                creationflags=_CREATE_NO_WINDOW, timeout=5,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
        out = (proc.stdout or "").strip()
        if proc.returncode == 0 and out:
            return out.splitlines()[0].strip(), ""
        err = (proc.stderr or "").strip()
        last_error = err or "Tailscale is installed but not logged in / running."
    return "", last_error


# =====================================================================
# TAILSCALE IP DETECTION (fallback only — the real app uses
# core.services.tailscale_service.TailscaleService via
# manager.container.tailscale_service; see ui.py. This stays here so
# the module still shows *something* when run standalone/outside the
# full app, same spirit as the `core.paths` fallback above.)
# =====================================================================

TAILSCALE_CANDIDATES = [
    "tailscale",
    r"C:\Program Files\Tailscale\tailscale.exe",
    r"C:\Program Files (x86)\Tailscale\tailscale.exe",
]


def get_tailscale_ip_fallback() -> tuple[str, str]:
    """Returns (ip, error). Only used when core.services.tailscale_service
    isn't available (see note above)."""
    last_error = "Tailscale CLI not found."
    for exe in TAILSCALE_CANDIDATES:
        try:
            proc = subprocess.run(
                [exe, "ip", "-4"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                creationflags=_CREATE_NO_WINDOW, timeout=5,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
        out = (proc.stdout or "").strip()
        if proc.returncode == 0 and out:
            return out.splitlines()[0].strip(), ""
        err = (proc.stderr or "").strip()
        last_error = err or "Tailscale is installed but not logged in / running."
    return "", last_error


# =====================================================================
# OFFICIAL VERSION LIST + DOWNLOAD METADATA
# =====================================================================

@dataclass
class MCVersion:
    id: str
    type: str  # "release" | "snapshot" | "old_beta" | "old_alpha"
    meta_url: str


def list_versions() -> tuple[list[MCVersion], str]:
    """Blocking — call off the UI thread. Returns (versions, error)."""
    try:
        resp = requests.get(VERSION_MANIFEST_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        return [], f"Couldn't reach Mojang's version list: {e}"
    except ValueError:
        return [], "Mojang's version list wasn't valid JSON."

    versions = [
        MCVersion(id=v["id"], type=v["type"], meta_url=v["url"])
        for v in data.get("versions", [])
        if "id" in v and "url" in v
    ]
    return versions, ""


@dataclass
class ServerDownloadInfo:
    url: str
    sha1: str
    size: int


def get_server_download_info(version: MCVersion) -> tuple[ServerDownloadInfo | None, str]:
    """Blocking — call off the UI thread. Returns (info, error)."""
    try:
        resp = requests.get(version.meta_url, timeout=15)
        resp.raise_for_status()
        meta = resp.json()
    except requests.RequestException as e:
        return None, f"Couldn't read version metadata: {e}"
    except ValueError:
        return None, "Version metadata wasn't valid JSON."

    server = meta.get("downloads", {}).get("server")
    if not server or "url" not in server:
        return None, f"Version {version.id} has no official server download (client-only release)."
    return ServerDownloadInfo(
        url=server["url"], sha1=server.get("sha1", ""), size=int(server.get("size", 0)),
    ), ""


# =====================================================================
# SERVER JAR DOWNLOAD (background, progress + SHA1 verification)
# =====================================================================

@dataclass
class DownloadEvent:
    kind: str  # "progress" | "done" | "error"
    downloaded: int = 0
    total: int = 0
    message: str = ""


class ServerDownloadWorker(threading.Thread):

    def __init__(self, download: ServerDownloadInfo, dest_dir: Path):
        super().__init__(daemon=True)
        self.download = download
        self.dest_dir = dest_dir
        self.events: "queue.Queue[DownloadEvent]" = queue.Queue()

    def run(self) -> None:
        try:
            self._run()
        except Exception as e:  # noqa: BLE001 — surface anything unexpected to the UI
            self.events.put(DownloadEvent(kind="error", message=str(e)))

    def _run(self) -> None:
        self.dest_dir.mkdir(parents=True, exist_ok=True)
        dest = self.dest_dir / "server.jar"
        tmp = self.dest_dir / "server.jar.part"

        with requests.get(self.download.url, stream=True, timeout=30) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or self.download.size or 0)
            downloaded = 0
            digest = hashlib.sha1()
            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    self.events.put(DownloadEvent(kind="progress", downloaded=downloaded, total=total))

        if self.download.sha1 and digest.hexdigest() != self.download.sha1:
            tmp.unlink(missing_ok=True)
            self.events.put(DownloadEvent(
                kind="error",
                message="Downloaded file failed hash verification against Mojang's metadata — try again.",
            ))
            return

        tmp.replace(dest)
        self.events.put(DownloadEvent(kind="done", message="server.jar downloaded and verified."))


# =====================================================================
# BEDROCK: OFFICIAL DOWNLOAD LINKS + DOWNLOAD/EXTRACT
# =====================================================================

@dataclass
class BedrockDownloadInfo:
    url: str
    version: str


def _bedrock_download_type(preview: bool) -> str:
    is_windows = platform.system() == "Windows"
    if is_windows:
        return "serverBedrockPreviewWindows" if preview else "serverBedrockWindows"
    return "serverBedrockPreviewLinux" if preview else "serverBedrockLinux"


def get_bedrock_download_info(preview: bool = False) -> tuple[BedrockDownloadInfo | None, str]:
    """Blocking — call off the UI thread. Returns (info, error). Unlike
    Java's version manifest, this only ever returns the *latest*
    build for the chosen channel — Mojang doesn't publish an archive
    of older Bedrock builds the way it does for Java."""
    try:
        resp = requests.get(BEDROCK_LINKS_URL, timeout=15, headers=_BEDROCK_HEADERS)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        return None, f"Couldn't reach Mojang's Bedrock download API: {e}"
    except ValueError:
        return None, "Bedrock download API didn't return valid JSON."

    want_type = _bedrock_download_type(preview)
    links = data.get("result", {}).get("links", [])
    url = next((link.get("downloadUrl") for link in links if link.get("downloadType") == want_type), None)
    if not url:
        return None, f"No {'preview ' if preview else ''}Bedrock server build was listed for this platform."

    m = re.search(r"bedrock-server-([\d.]+)\.zip", url)
    version = m.group(1) if m else "unknown"
    return BedrockDownloadInfo(url=url, version=version), ""


def bedrock_executable_name() -> str:
    return "bedrock_server.exe" if platform.system() == "Windows" else "bedrock_server"


# Top-level files/folders that hold *user* data (worlds, config, allow
# list) rather than server binaries — preserved across updates instead
# of being overwritten by the fresh zip contents.
_BEDROCK_PRESERVE_ON_UPDATE = {"worlds", "server.properties", "allowlist.json", "permissions.json"}


def _extract_bedrock_zip(zip_path: Path, dest_dir: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            top = member.split("/")[0]
            target = dest_dir / member
            if top in _BEDROCK_PRESERVE_ON_UPDATE and target.exists():
                continue  # keep the existing world/config instead of overwriting it
            if member.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as out:
                out.write(src.read())


class BedrockDownloadWorker(threading.Thread):
    """Downloads the Bedrock zip and extracts it in place. Mojang's
    Bedrock API doesn't publish a checksum the way the Java version
    manifest does, so there's no hash to verify against — integrity
    here just means the download completed and the zip opened cleanly."""

    def __init__(self, download: BedrockDownloadInfo, dest_dir: Path):
        super().__init__(daemon=True)
        self.download = download
        self.dest_dir = dest_dir
        self.events: "queue.Queue[DownloadEvent]" = queue.Queue()

    def run(self) -> None:
        try:
            self._run()
        except Exception as e:  # noqa: BLE001 — surface anything unexpected to the UI
            self.events.put(DownloadEvent(kind="error", message=str(e)))

    def _run(self) -> None:
        self.dest_dir.mkdir(parents=True, exist_ok=True)
        tmp_zip = self.dest_dir / "_bedrock_download.part.zip"

        with requests.get(self.download.url, stream=True, timeout=30, headers=_BEDROCK_HEADERS) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            with open(tmp_zip, "wb") as f:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    self.events.put(DownloadEvent(kind="progress", downloaded=downloaded, total=total))

        self.events.put(DownloadEvent(kind="progress", downloaded=downloaded, total=total,
                                      message="Extracting…"))
        try:
            _extract_bedrock_zip(tmp_zip, self.dest_dir)
        except zipfile.BadZipFile:
            tmp_zip.unlink(missing_ok=True)
            self.events.put(DownloadEvent(kind="error", message="Downloaded file wasn't a valid zip — try again."))
            return
        finally:
            tmp_zip.unlink(missing_ok=True)

        if platform.system() != "Windows":
            exe = self.dest_dir / "bedrock_server"
            if exe.exists():
                exe.chmod(exe.stat().st_mode | 0o111)

        self.events.put(DownloadEvent(
            kind="done",
            message=f"Bedrock server {self.download.version} downloaded and installed.",
        ))


# =====================================================================
# EULA + server.properties
# =====================================================================

def write_eula(server_dir: Path) -> None:
    """Only ever called after the user has explicitly checked the
    'I agree to the EULA' box in the UI — see ui.py."""
    server_dir.mkdir(parents=True, exist_ok=True)
    text = (
        "# By changing the setting below to TRUE you are indicating your agreement "
        f"to Mojang's EULA ({EULA_URL}).\n"
        "eula=true\n"
    )
    (server_dir / "eula.txt").write_text(text, encoding="utf-8")


def eula_accepted(server_dir: Path) -> bool:
    f = server_dir / "eula.txt"
    if not f.exists():
        return False
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().lower() == "eula=true":
            return True
    return False


def write_bedrock_eula_ack(server_dir: Path) -> None:
    """Bedrock Dedicated Server has no eula.txt gate the way the Java
    server does — Mojang has the user accept on the download page
    instead. This file is just this app's own record that the 'I
    agree to Mojang's EULA' box was checked here before downloading,
    so the Console tab's readiness check works the same for both
    editions. Only ever called after that box is checked — see ui.py."""
    server_dir.mkdir(parents=True, exist_ok=True)
    text = (
        "# This file records that the 'I agree to Mojang's EULA' box in "
        "Minecraft Server Manager was checked before this Bedrock server "
        f"was downloaded. Bedrock Dedicated Server itself doesn't read this "
        f"file; agreement to Mojang's EULA ({EULA_URL}) happens on Mojang's "
        "own download page.\n"
        "acknowledged=true\n"
    )
    (server_dir / "eula_ack.txt").write_text(text, encoding="utf-8")


def bedrock_eula_acknowledged(server_dir: Path) -> bool:
    return (server_dir / "eula_ack.txt").exists()


def read_server_properties(server_dir: Path) -> dict:
    props: dict[str, str] = {}
    f = server_dir / "server.properties"
    if f.exists():
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            props[k.strip()] = v.strip()
    return props


def update_server_properties(server_dir: Path, updates: dict) -> None:
    """Only takes effect on the next server start — server.properties
    is read once at boot."""
    server_dir.mkdir(parents=True, exist_ok=True)
    f = server_dir / "server.properties"
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines() if f.exists() else []
    seen = set()
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    f.write_text("\n".join(out) + "\n", encoding="utf-8")


# =====================================================================
# THE SERVER PROCESS ITSELF (persistent, not a one-shot worker)
# =====================================================================

_READY_RE = re.compile(r"Done \([\d.]+s\)! For help")
_JOIN_RE = re.compile(r": ([A-Za-z0-9_]{1,16}) joined the game")
_LEAVE_RE = re.compile(r": ([A-Za-z0-9_]{1,16}) left the game")

# Bedrock's console output looks nothing like Java's — different ready
# line, and joins/leaves are reported as "Player connected/disconnected"
# rather than "X joined/left the game".
_BEDROCK_READY_RE = re.compile(r"Server started\.")
_BEDROCK_JOIN_RE = re.compile(r"Player connected: ([^,]+),")
_BEDROCK_LEAVE_RE = re.compile(r"Player disconnected: ([^,]+),")


@dataclass
class ServerEvent:
    kind: str  # "log" | "ready" | "player_join" | "player_leave" | "stopped"
    message: str = ""
    player: str = ""
    exit_code: int | None = None


class MinecraftServerProcess:
    """One instance per running (or most-recently-run) server. The
    console/command UI polls `.events` the same way the rest of the
    app polls worker queues, but this process stays alive across many
    polls instead of finishing after one job."""

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.events: "queue.Queue[ServerEvent]" = queue.Queue()
        self.players: set[str] = set()
        self.started_at: float | None = None
        self.edition: str = "java"

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, server_dir: Path, min_mb: int, max_mb: int,
              java_path: str = "java", extra_args: str = "", edition: str = "java") -> str:
        """Returns an error message, or "" on success. `min_mb`/`max_mb`/
        `java_path`/`extra_args` are ignored for edition="bedrock" —
        the native bedrock_server binary doesn't take JVM heap flags."""
        if self.running:
            return "Server is already running."

        popen_kwargs: dict = dict(
            cwd=str(server_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        if platform.system() == "Windows":
            popen_kwargs["creationflags"] = _CREATE_NO_WINDOW

        if edition == "bedrock":
            exe = server_dir / bedrock_executable_name()
            if not exe.exists():
                return "bedrock_server wasn't found — download it from the Setup tab first."
            args = [str(exe)]
            if platform.system() != "Windows":
                import os
                env = os.environ.copy()
                env["LD_LIBRARY_PATH"] = "."
                popen_kwargs["env"] = env
        else:
            jar = server_dir / "server.jar"
            if not jar.exists():
                return "server.jar wasn't found — download it from the Setup tab first."
            args = [java_path, f"-Xms{min_mb}M", f"-Xmx{max_mb}M"]
            if extra_args.strip():
                args += extra_args.split()
            args += ["-jar", "server.jar", "nogui"]

        try:
            self.proc = subprocess.Popen(args, **popen_kwargs)
        except OSError as e:
            self.proc = None
            return f"Couldn't start the server: {e}"

        self.edition = edition
        self.players.clear()
        self.started_at = time.time()
        threading.Thread(target=self._read_loop, daemon=True).start()
        return ""

    def _read_loop(self) -> None:
        proc = self.proc
        assert proc is not None and proc.stdout is not None
        if self.edition == "bedrock":
            ready_re, join_re, leave_re = _BEDROCK_READY_RE, _BEDROCK_JOIN_RE, _BEDROCK_LEAVE_RE
        else:
            ready_re, join_re, leave_re = _READY_RE, _JOIN_RE, _LEAVE_RE
        for raw_line in proc.stdout:
            line = raw_line.rstrip("\r\n")
            if not line:
                continue
            self.events.put(ServerEvent(kind="log", message=line))
            if ready_re.search(line):
                self.events.put(ServerEvent(kind="ready", message=line))
            m = join_re.search(line)
            if m:
                self.players.add(m.group(1))
                self.events.put(ServerEvent(kind="player_join", player=m.group(1)))
            m = leave_re.search(line)
            if m:
                self.players.discard(m.group(1))
                self.events.put(ServerEvent(kind="player_leave", player=m.group(1)))
        exit_code = proc.wait() if proc else None
        self.events.put(ServerEvent(kind="stopped", exit_code=exit_code))
        self.proc = None
        self.started_at = None

    def send(self, command: str) -> bool:
        if not self.running or self.proc.stdin is None:
            return False
        try:
            self.proc.stdin.write(command.rstrip("\n") + "\n")
            self.proc.stdin.flush()
            return True
        except OSError:
            return False

    def stop(self, graceful: bool = True) -> None:
        if not self.running:
            return
        if graceful:
            self.send("stop")
        else:
            self.proc.kill()
