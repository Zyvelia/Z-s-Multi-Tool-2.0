"""
App Installer — core logic.

Thin wrapper around Windows Package Manager (winget), which ships with
Windows 11. Using winget instead of hand-maintained download URLs means:
  - installers always come from the publisher's registered winget source
    (or the Microsoft Store), never a scraped/guessed link
  - no per-app URL to keep updated when a vendor changes their site
  - winget itself verifies package hashes before install

Runs winget as a subprocess on a background thread and streams its
stdout back to the UI thread as ProgressEvents via a thread-safe queue,
matching the shared worker convention used elsewhere in the app
(see modules/folder_shredder/shredder.py).
"""

from __future__ import annotations

import json
import queue
import re
import shlex
import shutil
import subprocess
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:
    # Project convention: user-data lives under %APPDATA%\ZsMultiTool\
    # via core/paths.py. Falling back below keeps this module usable
    # standalone (e.g. outside the full app, or during testing).
    from core import paths  # type: ignore

    def _custom_apps_file() -> Path:
        return Path(paths.data_path("app_installer", "custom_apps.json"))
except ImportError:  # pragma: no cover - fallback for standalone use/testing
    def _custom_apps_file() -> Path:
        import os
        base = Path(os.environ.get("APPDATA", Path.home())) / "ZsMultiTool" / "app_installer"
        base.mkdir(parents=True, exist_ok=True)
        return base / "custom_apps.json"


def winget_available() -> bool:
    return shutil.which("winget") is not None


@dataclass
class AppResult:
    name: str
    id: str
    version: str = ""
    source: str = ""


@dataclass
class ProgressEvent:
    kind: str  # "log" | "search_done" | "overall_done" | "fatal_error"
    message: str = ""
    results: list[AppResult] = field(default_factory=list)
    ok: bool = True


@dataclass
class CustomApp:
    name: str
    command: str  # full command line, e.g. "winget install --id Foo.Bar -e --silent"
    category: str = "Utilities"  # which QUICK_APPS_BY_CATEGORY tab this shows up in


def load_custom_apps() -> list[CustomApp]:
    path = _custom_apps_file()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [
            CustomApp(
                name=item["name"],
                command=item["command"],
                category=item.get("category", "Utilities"),
            )
            for item in raw
        ]
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        return []


def save_custom_apps(apps: list[CustomApp]) -> None:
    path = _custom_apps_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(app) for app in apps], indent=2),
        encoding="utf-8",
    )


# A curated list of common apps for one-click buttons, grouped by category.
# IDs are winget package identifiers — winget search "<name>" to find more
# or double check one before relying on it, since publishers occasionally
# rename/retire IDs.
QUICK_APPS_BY_CATEGORY: dict[str, list[tuple[str, str]]] = {
    "Browsers": [
        ("Google Chrome", "Google.Chrome"),
        ("Mozilla Firefox", "Mozilla.Firefox"),
        ("Microsoft Edge", "Microsoft.Edge"),
        ("Brave", "Brave.Brave"),
        ("Opera GX", "Opera.OperaGX"),
        ("Vivaldi", "VivaldiTechnologies.Vivaldi"),
    ],
    "Chat & Social": [
        ("Discord", "Discord.Discord"),
        ("Slack", "SlackTechnologies.Slack"),
        ("Telegram", "Telegram.TelegramDesktop"),
        ("WhatsApp", "WhatsApp.WhatsApp"),
        ("Zoom", "Zoom.Zoom"),
        ("Microsoft Teams", "Microsoft.Teams"),
        ("Skype", "Microsoft.Skype"),
        ("Signal", "OpenWhisperSystems.Signal"),
    ],
    "Gaming": [
        ("Steam", "Valve.Steam"),
        ("Epic Games Launcher", "EpicGames.EpicGamesLauncher"),
        ("GOG Galaxy", "GOG.Galaxy"),
        ("Battle.net", "Blizzard.BattleNet"),
        ("EA app", "ElectronicArts.EADesktop"),
        ("Ubisoft Connect", "Ubisoft.Connect"),
        ("Xbox", "Microsoft.GamingApp"),
    ],
    "Media": [
        ("VLC", "VideoLAN.VLC"),
        ("Spotify", "Spotify.Spotify"),
        ("OBS Studio", "OBSProject.OBSStudio"),
        ("iTunes", "Apple.iTunes"),
        ("HandBrake", "HandBrake.HandBrake"),
        ("Audacity", "Audacity.Audacity"),
        ("foobar2000", "PeterPawlowski.foobar2000"),
        ("MPC-HC", "clsid2.mpc-hc"),
    ],
    "Dev Tools": [
        ("VS Code", "Microsoft.VisualStudioCode"),
        ("Git", "Git.Git"),
        ("Python 3", "Python.Python.3.13"),
        ("Node.js LTS", "OpenJS.NodeJS.LTS"),
        ("Docker Desktop", "Docker.DockerDesktop"),
        ("Windows Terminal", "Microsoft.WindowsTerminal"),
        ("GitHub Desktop", "GitHub.GitHubDesktop"),
        ("Postman", "Postman.Postman"),
        ("JetBrains Toolbox", "JetBrains.Toolbox"),
        ("Notepad++", "Notepad++.Notepad++"),
    ],
    "Utilities": [
        ("7-Zip", "7zip.7zip"),
        ("WinRAR", "RARLab.WinRAR"),
        ("PowerToys", "Microsoft.PowerToys"),
        ("Everything (search)", "voidtools.Everything"),
        ("CPU-Z", "CPUID.CPU-Z"),
        ("qBittorrent", "qBittorrent.qBittorrent"),
        ("TeamViewer", "TeamViewer.TeamViewer"),
        ("Rufus", "Rufus.Rufus"),
        ("Malwarebytes", "Malwarebytes.Malwarebytes"),
        ("CCleaner", "Piriform.CCleaner"),
    ],
    "Productivity": [
        ("Notion", "Notion.Notion"),
        ("Obsidian", "Obsidian.Obsidian"),
        ("Microsoft 365", "Microsoft.Office"),
        ("Adobe Acrobat Reader", "Adobe.Acrobat.Reader.64-bit"),
        ("LibreOffice", "TheDocumentFoundation.LibreOffice"),
        ("Google Drive", "Google.GoogleDrive"),
        ("Dropbox", "Dropbox.Dropbox"),
    ],
}

# Flattened view, kept for any code that just wants the full list.
QUICK_APPS: list[tuple[str, str]] = [
    app for apps in QUICK_APPS_BY_CATEGORY.values() for app in apps
]

_CREATE_NO_WINDOW = 0x08000000


def _run_captured(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_CREATE_NO_WINDOW,
        timeout=60,
    )


_ROW_SPLIT = re.compile(r"\s{2,}")


def _parse_search_table(output: str) -> list[AppResult]:
    """Parse winget's fixed-width search table into AppResults."""
    lines = [ln for ln in output.splitlines() if ln.strip()]
    header_idx = None
    for i, ln in enumerate(lines):
        if ln.lower().startswith("name") and "id" in ln.lower():
            header_idx = i
            break
    if header_idx is None:
        return []

    header = lines[header_idx]
    # column starts, derived from header field positions
    id_col = header.lower().index("id")
    version_col = header.lower().find("version")
    source_col = header.lower().find("source")

    results: list[AppResult] = []
    for ln in lines[header_idx + 2:]:  # skip header + separator row
        if set(ln.strip()) <= {"-"}:
            continue
        name = ln[:id_col].strip()
        rest = ln[id_col:]
        if version_col > id_col:
            pkg_id = ln[id_col:version_col].strip()
        else:
            pkg_id = rest.strip().split(" ")[0]
        version = ""
        source = ""
        if version_col > id_col:
            if source_col > version_col:
                version = ln[version_col:source_col].strip()
                source = ln[source_col:].strip()
            else:
                version = ln[version_col:].strip()
        if name and pkg_id:
            results.append(AppResult(name=name, id=pkg_id, version=version, source=source))
    return results


def search_apps(query: str) -> tuple[list[AppResult], str]:
    """Blocking search — call off the UI thread. Returns (results, error)."""
    if not query.strip():
        return [], "Enter a search term."
    try:
        proc = _run_captured(["winget", "search", query, "--accept-source-agreements"])
    except FileNotFoundError:
        return [], "winget was not found on this system."
    except subprocess.TimeoutExpired:
        return [], "Search timed out."
    if proc.returncode != 0 and not proc.stdout:
        return [], (proc.stderr.strip() or "Search failed.")
    return _parse_search_table(proc.stdout), ""


def _stream_command(args: list[str], events: "queue.Queue[ProgressEvent]") -> None:
    """Runs args as a subprocess, pushing log/overall_done/fatal_error
    ProgressEvents to the given queue. Shared by InstallWorker (winget)
    and CommandWorker (user-defined custom commands)."""
    if not args:
        events.put(ProgressEvent(kind="fatal_error", message="Empty command."))
        return

    events.put(ProgressEvent(kind="log", message=f"$ {' '.join(args)}"))
    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_CREATE_NO_WINDOW,
            bufsize=1,
        )
    except FileNotFoundError:
        events.put(ProgressEvent(kind="fatal_error", message=f"'{args[0]}' was not found."))
        return
    except Exception as e:  # noqa: BLE001
        events.put(ProgressEvent(kind="fatal_error", message=str(e)))
        return

    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.rstrip("\r\n")
        if line.strip():
            events.put(ProgressEvent(kind="log", message=line))
    returncode = proc.wait()

    if returncode == 0:
        events.put(ProgressEvent(kind="overall_done", ok=True, message="Installed successfully."))
    else:
        events.put(ProgressEvent(
            kind="overall_done", ok=False,
            message=f"Command exited with code {returncode}.",
        ))


class InstallWorker(threading.Thread):
    """Runs `winget install` for one curated/searched package."""

    def __init__(self, package_id: str):
        super().__init__(daemon=True)
        self.package_id = package_id
        self.events: queue.Queue[ProgressEvent] = queue.Queue()

    def run(self) -> None:
        if not winget_available():
            self.events.put(ProgressEvent(
                kind="fatal_error",
                message=(
                    "winget was not found. Install 'App Installer' from the "
                    "Microsoft Store, then try again."
                ),
            ))
            return

        args = [
            "winget", "install", "--id", self.package_id, "-e",
            "--accept-package-agreements", "--accept-source-agreements",
            "--silent",
        ]
        _stream_command(args, self.events)


class CommandWorker(threading.Thread):
    """Runs a user-supplied custom install command (e.g. a full winget
    line, or any other CLI installer invocation) exactly as typed."""

    def __init__(self, command: str):
        super().__init__(daemon=True)
        self.command = command
        self.events: queue.Queue[ProgressEvent] = queue.Queue()

    def run(self) -> None:
        try:
            args = shlex.split(self.command, posix=False)
            # shlex(posix=False) keeps surrounding quotes; strip them per-token.
            args = [a[1:-1] if len(a) >= 2 and a[0] == a[-1] == '"' else a for a in args]
        except ValueError as e:
            self.events.put(ProgressEvent(kind="fatal_error", message=f"Couldn't parse command: {e}"))
            return
        _stream_command(args, self.events)


class SearchWorker(threading.Thread):
    """Runs `winget search` off the UI thread."""

    def __init__(self, query: str):
        super().__init__(daemon=True)
        self.query = query
        self.events: queue.Queue[ProgressEvent] = queue.Queue()

    def run(self) -> None:
        results, error = search_apps(self.query)
        if error:
            self.events.put(ProgressEvent(kind="fatal_error", message=error))
        else:
            self.events.put(ProgressEvent(kind="search_done", results=results))
