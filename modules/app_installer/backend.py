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
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:
    # Project convention: user-data lives under %APPDATA%\ZsMultiTool\
    # via core/paths.py. Falling back below keeps this module usable
    # standalone (e.g. outside the full app, or during testing).
    from core import paths  # type: ignore

    def _data_file(name: str) -> Path:
        return Path(paths.data_path("app_installer", name))
except ImportError:  # pragma: no cover - fallback for standalone use/testing
    def _data_file(name: str) -> Path:
        import os
        base = Path(os.environ.get("APPDATA", Path.home())) / "ZsMultiTool" / "app_installer"
        base.mkdir(parents=True, exist_ok=True)
        return base / name


def _custom_apps_file() -> Path:
    return _data_file("custom_apps.json")


def _button_order_file() -> Path:
    return _data_file("button_order.json")


def _hidden_quick_apps_file() -> Path:
    return _data_file("hidden_quick_apps.json")


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
    id: str = field(default_factory=lambda: uuid.uuid4().hex)  # stable key for drag ordering


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
                # Older save files predate the id field — generate one on
                # load so existing custom apps still get a stable key.
                id=item.get("id") or uuid.uuid4().hex,
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


# ---------------------------------------------------------------- ordering
# Buttons in a category tab (curated apps *and* custom apps, interleaved)
# can be freely drag-reordered by the user. That combined order is
# persisted as {category: [key, key, ...]} where each key is
# "quick:<pkg_id>" or "custom:<custom_app_id>", and merged over the
# hardcoded/insertion-order defaults whenever the grid is built.

@dataclass
class ButtonEntry:
    """One button in a category grid, either a curated (quick) app or a
    user-defined custom app — whichever it is, `key` is stable and unique
    within the category, for drag-reorder persistence."""
    kind: str  # "quick" | "custom"
    key: str
    name: str
    quick_pkg_id: str | None = None
    custom_app: "CustomApp | None" = None


def load_button_order() -> dict[str, list[str]]:
    path = _button_order_file()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return {
            str(category): [str(key) for key in keys]
            for category, keys in raw.items()
        }
    except (json.JSONDecodeError, OSError, TypeError):
        return {}


def save_button_order(order: dict[str, list[str]]) -> None:
    path = _button_order_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(order, indent=2), encoding="utf-8")


def get_ordered_entries(
    category: str,
    custom_apps: list[CustomApp],
    order: dict[str, list[str]],
    hidden_quick_apps: dict[str, list[str]] | None = None,
) -> list[ButtonEntry]:
    """Returns every button entry for `category` (curated + custom) in the
    user's saved drag order, falling back to curated-then-custom insertion
    order for anything not yet in the saved order. Entries whose underlying
    app no longer exists (removed custom app, retired curated id, or a
    curated id the user removed via right-click) are silently dropped;
    anything new is appended at the end so it's never lost, just shows up
    last until dragged into place."""
    hidden_ids = set((hidden_quick_apps or {}).get(category, []))
    quick_defaults = [
        (name, pkg_id)
        for name, pkg_id in QUICK_APPS_BY_CATEGORY.get(category, [])
        if pkg_id not in hidden_ids
    ]
    custom_in_category = [a for a in custom_apps if a.category == category]

    by_key: dict[str, ButtonEntry] = {}
    default_order: list[str] = []
    for name, pkg_id in quick_defaults:
        key = f"quick:{pkg_id}"
        by_key[key] = ButtonEntry(kind="quick", key=key, name=name, quick_pkg_id=pkg_id)
        default_order.append(key)
    for app in custom_in_category:
        key = f"custom:{app.id}"
        by_key[key] = ButtonEntry(kind="custom", key=key, name=app.name, custom_app=app)
        default_order.append(key)

    saved = order.get(category, [])
    ordered_keys = [key for key in saved if key in by_key]
    ordered_keys += [key for key in default_order if key not in ordered_keys]

    return [by_key[key] for key in ordered_keys]


def load_hidden_quick_apps() -> dict[str, list[str]]:
    """Curated apps the user removed via right-click, per category. Kept
    separate from custom apps since these are hides of built-in entries,
    not user-created ones — 'un-hiding' isn't exposed in the UI yet, but
    the data model supports it if that's ever wanted."""
    path = _hidden_quick_apps_file()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return {
            str(category): [str(pkg_id) for pkg_id in pkg_ids]
            for category, pkg_ids in raw.items()
        }
    except (json.JSONDecodeError, OSError, TypeError):
        return {}


def save_hidden_quick_apps(hidden: dict[str, list[str]]) -> None:
    path = _hidden_quick_apps_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(hidden, indent=2), encoding="utf-8")

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


@dataclass
class RiskAssessment:
    level: str  # "safe" | "caution" | "dangerous"
    reasons: list[str] = field(default_factory=list)


# Patterns that indicate a command is likely to destroy data, wipe a disk,
# tamper with system security, or blindly execute unreviewed remote code.
# This is a heuristic, best-effort check — not a sandbox and not a guarantee.
# It exists to catch obvious mistakes/copy-paste accidents, not to defend
# against a determined attacker who controls the command text.
_DANGEROUS_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\brm\s+.*-[a-z]*r[a-z]*f|\brm\s+.*-[a-z]*f[a-z]*r", re.I),
     "Recursive forced delete (rm -rf) — can wipe entire folder trees."),
    (re.compile(r"\bdel\s+.*/f.*/s|\bdel\s+.*/s.*/f", re.I),
     "Forced recursive delete (del /f /s) — can wipe entire folder trees."),
    (re.compile(r"\brd\s+.*/s|\brmdir\s+.*/s", re.I),
     "Recursive directory removal (rmdir /s)."),
    (re.compile(r"\bformat\s+[a-z]:", re.I),
     "Formats a disk drive."),
    (re.compile(r"\bmkfs(\.\w+)?\b", re.I),
     "Creates a new filesystem, destroying existing data on the target."),
    (re.compile(r"\bdd\s+.*\bof=", re.I),
     "Low-level disk write (dd) — can overwrite a drive or partition."),
    (re.compile(r"\bdiskpart\b", re.I),
     "Invokes diskpart, which can repartition or wipe disks."),
    (re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),
     "Fork bomb pattern — will exhaust system resources."),
    (re.compile(r"\breg\s+delete\b", re.I),
     "Deletes registry keys."),
    (re.compile(r"\btakeown\b.*\bsystem32\b|\bicacls\b.*\bsystem32\b", re.I),
     "Changes ownership/permissions on Windows system files."),
    (re.compile(r"\bnet\s+user\s+\S+\s+.*\/add", re.I),
     "Creates a new user account."),
    (re.compile(r"\bnet\s+localgroup\s+administrators\b", re.I),
     "Modifies the local Administrators group."),
    (re.compile(r"disable.*(defender|firewall)|firewall.*off|Set-MpPreference", re.I),
     "Disables Windows security features."),
    (re.compile(r"-EncodedCommand\b", re.I),
     "Obfuscated/base64-encoded PowerShell — contents can't be reviewed as typed."),
    (re.compile(r"\biex\b|\bInvoke-Expression\b", re.I),
     "Executes dynamically-fetched code (Invoke-Expression)."),
    (re.compile(r"(curl|wget|iwr|Invoke-WebRequest).*\|\s*(sh|bash|powershell|iex)", re.I),
     "Downloads a remote script and pipes it straight into a shell, unreviewed."),
    (re.compile(r"shutdown\s+/s|shutdown\s+/r|\bshutdown\s+-h\b", re.I),
     "Shuts down or restarts the machine."),
]

# Softer signals: not necessarily harmful, but worth a heads-up because
# they fall outside the "run a normal installer" pattern.
_CAUTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^(curl|wget|iwr|Invoke-WebRequest)\b", re.I),
     "Downloads a file directly from a URL rather than using a package manager."),
    (re.compile(r"\bpowershell\b", re.I),
     "Runs a PowerShell command/script."),
    (re.compile(r"\bsudo\b|\brunas\b", re.I),
     "Requests elevated/administrator privileges."),
    (re.compile(r"http://", re.I),
     "Uses plain HTTP (unencrypted) rather than HTTPS."),
]

# Patterns that look like a normal, well-scoped app install — used only to
# give positive reassurance in the UI, not to override a dangerous match.
_LOOKS_LIKE_INSTALLER = re.compile(
    r"^\s*(winget\s+install|choco\s+install|scoop\s+install|msiexec\s+/i)\b", re.I
)


def assess_command_risk(command: str) -> RiskAssessment:
    """Best-effort heuristic scan of a custom command string. Returns a
    risk level and human-readable reasons. This does NOT execute or parse
    the command as a shell would (no expansion, no env var resolution) —
    it's a pattern match over the literal text the user typed, meant to
    catch obviously destructive or opaque commands before they run."""
    if not command.strip():
        return RiskAssessment(level="safe")

    dangerous_reasons = [msg for pat, msg in _DANGEROUS_PATTERNS if pat.search(command)]
    if dangerous_reasons:
        return RiskAssessment(level="dangerous", reasons=dangerous_reasons)

    caution_reasons = [msg for pat, msg in _CAUTION_PATTERNS if pat.search(command)]
    if caution_reasons and not _LOOKS_LIKE_INSTALLER.match(command):
        return RiskAssessment(level="caution", reasons=caution_reasons)

    return RiskAssessment(level="safe")


# ---------------------------------------------------------------- explain

# Known executables mapped to a function that takes their argv (excluding
# the executable itself) and returns a one-line plain-English description.
# This is best-effort/heuristic, same caveat as risk assessment: it reads
# the text, it doesn't actually resolve what will run.

def _find_flag_value(args: list[str], *flag_names: str) -> str | None:
    for i, a in enumerate(args):
        if a in flag_names and i + 1 < len(args):
            return args[i + 1]
    return None


def _has(args: list[str], *flag_names: str) -> bool:
    return any(a in flag_names for a in args)


def _explain_winget(args: list[str]) -> str:
    if _has(args, "install"):
        pkg = _find_flag_value(args, "--id", "-e")
        desc = "Uses winget (Windows Package Manager) to install a package"
        if pkg:
            desc += f" (ID: {pkg})"
        if _has(args, "--silent"):
            desc += ", silently with no prompts"
        return desc + "."
    if _has(args, "uninstall"):
        return "Uses winget to uninstall a package."
    if _has(args, "search"):
        return "Uses winget to search for a package (no changes made)."
    return f"Runs winget with arguments: {' '.join(args)}"


def _explain_choco(args: list[str]) -> str:
    if _has(args, "install"):
        pkgs = [a for a in args[1:] if not a.startswith("-")]
        return f"Uses Chocolatey to install: {', '.join(pkgs) or '(package name)'}."
    if _has(args, "uninstall"):
        return "Uses Chocolatey to uninstall a package."
    return f"Runs Chocolatey (choco) with arguments: {' '.join(args)}"


def _explain_scoop(args: list[str]) -> str:
    if _has(args, "install"):
        pkgs = [a for a in args[1:] if not a.startswith("-")]
        return f"Uses Scoop to install: {', '.join(pkgs) or '(package name)'}."
    return f"Runs Scoop with arguments: {' '.join(args)}"


def _explain_msiexec(args: list[str]) -> str:
    target = _find_flag_value(args, "/i", "-i") or next(
        (a for a in args if a.lower().endswith(".msi")), None
    )
    desc = "Runs the Windows Installer service"
    if target:
        desc += f" on '{target}'"
    if _has(args, "/quiet", "/qn", "-quiet"):
        desc += ", quietly with no UI"
    return desc + "."


def _explain_download(exe: str, args: list[str]) -> str:
    url = next((a for a in args if "://" in a), None)
    out = _find_flag_value(args, "-o", "-O", "--output", "-OutFile")
    desc = f"Downloads a file using {exe}"
    if url:
        desc += f" from {url}"
    if out:
        desc += f", saving it as '{out}'"
    return desc + "."


def _explain_powershell(args: list[str]) -> str:
    if any(a.lower() in ("-encodedcommand", "-enc") for a in args):
        return "Runs a base64-encoded PowerShell command — contents are not visible as typed."
    cmd = _find_flag_value(args, "-Command", "-command", "-c")
    if cmd:
        return f"Runs a PowerShell command: {cmd}"
    script = next((a for a in args if a.lower().endswith(".ps1")), None)
    if script:
        return f"Runs the PowerShell script '{script}'."
    return f"Runs PowerShell with arguments: {' '.join(args)}"


def _explain_delete(exe: str, args: list[str]) -> str:
    # rm uses "-flag" convention (unix); del/rd/rmdir/erase use "/flag" (Windows).
    flag_prefixes = ("-",) if exe == "rm" else ("-", "/")
    targets = [a for a in args if not a.startswith(flag_prefixes)]
    desc = f"Deletes files/folders using {exe}"
    if targets:
        desc += f", targeting: {', '.join(targets)}"
    return desc + "."


def _explain_net(args: list[str]) -> str:
    if args[:1] == ["user"] and "/add" in args:
        user = args[1] if len(args) > 1 else "(username)"
        return f"Creates a new Windows user account named '{user}'."
    if args[:1] == ["localgroup"]:
        return "Modifies a local Windows group (e.g. Administrators)."
    return f"Runs 'net' with arguments: {' '.join(args)}"


def _explain_reg(args: list[str]) -> str:
    if _has(args, "delete"):
        return "Deletes one or more Windows Registry keys."
    if _has(args, "add"):
        return "Adds or modifies a Windows Registry key/value."
    return f"Runs 'reg' with arguments: {' '.join(args)}"


_EXECUTABLE_EXPLAINERS: dict[str, "callable"] = {
    "winget": _explain_winget,
    "choco": _explain_choco,
    "choco.exe": _explain_choco,
    "scoop": _explain_scoop,
    "msiexec": _explain_msiexec,
    "curl": lambda a: _explain_download("curl", a),
    "wget": lambda a: _explain_download("wget", a),
    "iwr": lambda a: _explain_download("Invoke-WebRequest", a),
    "invoke-webrequest": lambda a: _explain_download("Invoke-WebRequest", a),
    "powershell": _explain_powershell,
    "pwsh": _explain_powershell,
    "rm": lambda a: _explain_delete("rm", a),
    "del": lambda a: _explain_delete("del", a),
    "erase": lambda a: _explain_delete("erase", a),
    "rd": lambda a: _explain_delete("rd", a),
    "rmdir": lambda a: _explain_delete("rmdir", a),
    "net": _explain_net,
    "reg": _explain_reg,
    "format": lambda a: f"Formats a disk drive ({' '.join(a) or '(no target given)'}).",
    "diskpart": lambda a: "Opens diskpart, which can repartition or wipe disks.",
    "dd": lambda a: "Performs a low-level disk write — can overwrite a drive or partition.",
    "shutdown": lambda a: "Shuts down or restarts the machine.",
    "taskkill": lambda a: f"Forcibly ends running process(es): {' '.join(a) or '(unspecified)'}",
    "schtasks": lambda a: "Creates, modifies, or deletes a scheduled task.",
    "vssadmin": lambda a: "Manages Volume Shadow Copies (can delete Windows backups/restore points).",
    "bcdedit": lambda a: "Modifies Windows boot configuration.",
    "certutil": lambda a: "Runs certutil — commonly used legitimately for certs, but also a known "
                            "way to smuggle/decode files past antivirus.",
}

_CONNECTOR_LABEL = {
    "&&": "then, if that succeeds, runs:",
    "||": "then, if that fails, runs:",
    ";": "then runs:",
    "|": "then pipes the output into:",
}


def _split_command_chain(command: str) -> list[tuple[str | None, str]]:
    """Best-effort split of a command line into (connector, segment) pairs
    on &&, ||, ; and |. Does not fully respect quoting — good enough for a
    human-readable preview, not a real shell parser."""
    tokens = re.split(r"(&&|\|\||;|\|)", command)
    segments: list[tuple[str | None, str]] = []
    connector: str | None = None
    for tok in tokens:
        stripped = tok.strip()
        if stripped in ("&&", "||", ";", "|"):
            connector = stripped
            continue
        if stripped:
            segments.append((connector, stripped))
            connector = None
    return segments


def _explain_segment(segment: str) -> str:
    try:
        args = shlex.split(segment, posix=False)
        args = [a[1:-1] if len(a) >= 2 and a[0] == a[-1] == '"' else a for a in args]
    except ValueError:
        return f"Runs: {segment}  (couldn't fully parse this — check it carefully)"
    if not args:
        return f"Runs: {segment}"

    exe = args[0].lower()
    if exe.endswith(".exe"):
        exe = exe[:-4]
    exe = exe.split("\\")[-1].split("/")[-1]  # strip any path prefix

    explainer = _EXECUTABLE_EXPLAINERS.get(exe)
    if explainer:
        return explainer(args[1:])

    if exe.endswith(".msi"):
        return f"Runs the Windows Installer package '{args[0]}'."
    if exe.endswith((".exe", "")) and len(args) == 1:
        return f"Runs the program '{args[0]}' with no arguments."
    return f"Runs the program '{args[0]}' with arguments: {' '.join(args[1:]) or '(none)'}"


def explain_command(command: str) -> list[str]:
    """Best-effort, human-readable breakdown of what a command line will
    do, step by step. Purely textual analysis — not a simulation or a
    guarantee of actual behavior, since env vars, aliases, PATH resolution,
    and shell quoting can all change what really executes."""
    command = command.strip()
    if not command:
        return []
    segments = _split_command_chain(command)
    lines: list[str] = []
    for i, (connector, seg) in enumerate(segments):
        prefix = "Runs:" if i == 0 or connector is None else _CONNECTOR_LABEL.get(connector, "then runs:")
        lines.append(f"{prefix} {_explain_segment(seg)}")
    return lines


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
