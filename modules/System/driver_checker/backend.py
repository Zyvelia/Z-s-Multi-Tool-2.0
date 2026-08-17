"""
Driver/Update Checker — core logic.

Three independent data sources, each optional and self-guarding so the
module degrades gracefully instead of crashing when something isn't
available:

  - Installed drivers: `Get-CimInstance Win32_PnPSignedDriver` via a
    PowerShell subprocess, parsed from JSON. Read-only, no admin needed.

  - Driver updates: the real Windows Update Agent (the same engine
    Settings > Windows Update uses), queried through pywin32's COM
    bridge for Type='Driver' updates that aren't installed yet. This
    only *lists* what's available — it never installs anything here.

  - Software updates: `winget upgrade`, parsed the same way
    modules/app_installer/backend.py parses `winget search` — a
    fixed-width table.

All subprocess calls hide their console window (CREATE_NO_WINDOW),
matching the convention used by modules/app_installer/backend.py.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass

try:
    import pythoncom
    import win32com.client
    WIN32COM_AVAILABLE = True
except ImportError:  # pragma: no cover - pywin32 not installed
    pythoncom = None  # type: ignore
    win32com = None  # type: ignore
    WIN32COM_AVAILABLE = False

_CREATE_NO_WINDOW = 0x08000000


def _run_captured(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_CREATE_NO_WINDOW,
        timeout=timeout,
    )


# =====================================================================
# INSTALLED DRIVERS
# =====================================================================

@dataclass
class DriverInfo:
    device_name: str
    version: str
    date: str
    manufacturer: str
    device_class: str


_WMI_DATE_RE = re.compile(r"/Date\((\d+)\)/")


def _format_wmi_date(raw: str | None) -> str:
    if not raw:
        return ""
    m = _WMI_DATE_RE.match(raw)
    if not m:
        return raw
    import datetime
    try:
        ts = int(m.group(1)) / 1000
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return raw


def list_installed_drivers() -> tuple[list[DriverInfo], str]:
    """Blocking — call off the UI thread. Returns (drivers, error)."""
    ps_command = (
        "Get-CimInstance Win32_PnPSignedDriver | "
        "Where-Object { $_.DeviceName } | "
        "Select-Object DeviceName, DriverVersion, DriverDate, Manufacturer, DeviceClass | "
        "ConvertTo-Json -Compress"
    )
    try:
        proc = _run_captured(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_command],
            timeout=45,
        )
    except FileNotFoundError:
        return [], "PowerShell was not found on this system."
    except subprocess.TimeoutExpired:
        return [], "Driver query timed out."

    if proc.returncode != 0 and not proc.stdout.strip():
        return [], (proc.stderr.strip() or "Driver query failed.")

    try:
        raw = json.loads(proc.stdout) if proc.stdout.strip() else []
    except json.JSONDecodeError:
        return [], "Couldn't parse driver list output."

    if isinstance(raw, dict):
        raw = [raw]

    drivers = [
        DriverInfo(
            device_name=item.get("DeviceName") or "(unnamed device)",
            version=item.get("DriverVersion") or "",
            date=_format_wmi_date(item.get("DriverDate")),
            manufacturer=item.get("Manufacturer") or "",
            device_class=item.get("DeviceClass") or "",
        )
        for item in raw
    ]
    drivers.sort(key=lambda d: d.device_name.lower())
    return drivers, ""


# =====================================================================
# DRIVER UPDATES — Windows Update Agent (COM)
# =====================================================================

@dataclass
class UpdateInfo:
    title: str
    description: str
    kb_articles: str = ""


def check_driver_updates() -> tuple[list[UpdateInfo], str]:
    """Blocking — call off a background thread; this can take a minute
    or more, since it's the same search Settings > Windows Update runs.
    Returns (updates, error)."""
    if not WIN32COM_AVAILABLE:
        return [], "Requires pywin32 (already listed in requirements.txt as a Windows-only dependency)."

    pythoncom.CoInitialize()
    try:
        session = win32com.client.Dispatch("Microsoft.Update.Session")
        searcher = session.CreateUpdateSearcher()
        result = searcher.Search("IsInstalled=0 and Type='Driver'")
        updates = []
        for u in result.Updates:
            try:
                kb = ", ".join(f"KB{k}" for k in u.KBArticleIDs) if u.KBArticleIDs else ""
            except Exception:
                kb = ""
            updates.append(UpdateInfo(title=u.Title, description=u.Description or "", kb_articles=kb))
        return updates, ""
    except Exception as e:  # noqa: BLE001 — COM errors vary widely, surface them as-is
        return [], f"Windows Update search failed: {e}"
    finally:
        pythoncom.CoUninitialize()


# =====================================================================
# SOFTWARE UPDATES — winget
# =====================================================================

@dataclass
class SoftwareUpdateInfo:
    name: str
    id: str
    current_version: str
    available_version: str
    source: str


def _winget_available() -> bool:
    import shutil
    return shutil.which("winget") is not None


def _parse_upgrade_table(output: str) -> list[SoftwareUpdateInfo]:
    lines = [ln for ln in output.splitlines() if ln.strip()]
    header_idx = None
    for i, ln in enumerate(lines):
        low = ln.lower()
        if low.startswith("name") and "id" in low and "version" in low:
            header_idx = i
            break
    if header_idx is None:
        return []

    header = lines[header_idx]
    id_col = header.lower().index("id")
    version_col = header.lower().find("version")
    available_col = header.lower().find("available")
    source_col = header.lower().find("source")

    cols = sorted(c for c in (id_col, version_col, available_col, source_col) if c >= 0)

    def _slice(start: int) -> str:
        idx = cols.index(start)
        end = cols[idx + 1] if idx + 1 < len(cols) else None
        return (start, end)

    results: list[SoftwareUpdateInfo] = []
    for ln in lines[header_idx + 2:]:
        if set(ln.strip()) <= {"-"}:
            continue
        if ln.strip().lower().startswith(("upgrades available", "no installed", "the following")):
            continue
        name = ln[:id_col].strip()
        pkg_id_start, pkg_id_end = _slice(id_col)
        pkg_id = ln[pkg_id_start:pkg_id_end].strip() if pkg_id_end else ln[pkg_id_start:].strip()
        current = ""
        available = ""
        source = ""
        if version_col >= 0:
            v_start, v_end = _slice(version_col)
            current = ln[v_start:v_end].strip() if v_end else ln[v_start:].strip()
        if available_col >= 0:
            a_start, a_end = _slice(available_col)
            available = ln[a_start:a_end].strip() if a_end else ln[a_start:].strip()
        if source_col >= 0:
            s_start, _s_end = _slice(source_col)
            source = ln[s_start:].strip()
        if name and pkg_id:
            results.append(SoftwareUpdateInfo(
                name=name, id=pkg_id, current_version=current,
                available_version=available, source=source,
            ))
    return results


def check_software_updates() -> tuple[list[SoftwareUpdateInfo], str]:
    """Blocking — call off the UI thread. Returns (updates, error)."""
    if not _winget_available():
        return [], "winget was not found on this system."
    try:
        proc = _run_captured(
            ["winget", "upgrade", "--accept-source-agreements", "--include-unknown"],
            timeout=90,
        )
    except subprocess.TimeoutExpired:
        return [], "winget upgrade timed out."
    if proc.returncode != 0 and not proc.stdout.strip():
        return [], (proc.stderr.strip() or "winget upgrade failed.")
    return _parse_upgrade_table(proc.stdout), ""
