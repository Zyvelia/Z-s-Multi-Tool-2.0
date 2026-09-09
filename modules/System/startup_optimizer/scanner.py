"""
Startup Optimizer — data collection.

Startup apps: reuses the exact non-destructive mechanism the old
Startup Manager module used (registry Run keys + Startup folder
shortcuts, toggled via the same "StartupApproved" flag Task Manager
writes — never requires admin, always reversible). A supplementary
PowerShell `Get-CimInstance Win32_StartupCommand` pass is merged in
read-only, to catch anything the registry scan alone might miss.

Services: enumerated via pywin32 (falls back to `sc query` output
parsing if pywin32 isn't installed). Start-type changes go through
`sc config` via subprocess, since pywin32's ChangeServiceConfig needs
a live handle juggling act that `sc` does more reliably.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

try:
    import winreg
    REGISTRY_AVAILABLE = True
except ImportError:  # pragma: no cover - non-Windows dev/test environment
    winreg = None  # type: ignore
    REGISTRY_AVAILABLE = False

try:
    import win32com.client
    WIN32COM_AVAILABLE = True
except ImportError:  # pragma: no cover
    win32com = None  # type: ignore
    WIN32COM_AVAILABLE = False

try:
    import win32serviceutil
    import win32service
    PYWIN32_SERVICE_AVAILABLE = True
except ImportError:  # pragma: no cover
    win32serviceutil = None  # type: ignore
    win32service = None  # type: ignore
    PYWIN32_SERVICE_AVAILABLE = False


# ---------------------------------------------------------------- startup apps

_RUN_KEYS = [
    (winreg.HKEY_CURRENT_USER if REGISTRY_AVAILABLE else None,
     r"Software\Microsoft\Windows\CurrentVersion\Run", "Registry (Current User)"),
    (winreg.HKEY_LOCAL_MACHINE if REGISTRY_AVAILABLE else None,
     r"Software\Microsoft\Windows\CurrentVersion\Run", "Registry (All Users)"),
    (winreg.HKEY_LOCAL_MACHINE if REGISTRY_AVAILABLE else None,
     r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", "Registry (All Users, 32-bit)"),
]

_APPROVED_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
_APPROVED_FOLDER_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"

_ENABLED_BYTE = 0x02
_DISABLED_BYTE = 0x03


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _startup_folders() -> list[tuple[Path, str]]:
    appdata = os.environ.get("APPDATA")
    programdata = os.environ.get("PROGRAMDATA")
    out = []
    if appdata:
        out.append((Path(appdata) / "Microsoft/Windows/Start Menu/Programs/Startup",
                     "Startup Folder (Current User)"))
    if programdata:
        out.append((Path(programdata) / "Microsoft/Windows/Start Menu/Programs/Startup",
                     "Startup Folder (All Users)"))
    return out


@dataclass
class StartupItem:
    name: str
    command: str
    source: str
    kind: str  # "registry" | "shortcut" | "info"
    enabled: bool
    hive: int | None = None
    subkey: str | None = None
    path: Path | None = None


def _read_approved(hive, subkey: str, value_name: str) -> bool | None:
    try:
        with winreg.OpenKey(hive, subkey) as key:
            data, _type = winreg.QueryValueEx(key, value_name)
            if isinstance(data, (bytes, bytearray)) and len(data) >= 1:
                return data[0] == _ENABLED_BYTE
    except OSError:
        pass
    return None


def _write_approved(hive, subkey: str, value_name: str, enabled: bool) -> None:
    with winreg.CreateKeyEx(hive, subkey) as key:
        blob = bytes([_ENABLED_BYTE if enabled else _DISABLED_BYTE]) + b"\x00" * 11
        winreg.SetValueEx(key, value_name, 0, winreg.REG_BINARY, blob)


def _resolve_shortcut_target(path: Path) -> str:
    if not WIN32COM_AVAILABLE or path.suffix.lower() != ".lnk":
        return path.name
    try:
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(str(path))
        target = shortcut.TargetPath or ""
        args = shortcut.Arguments or ""
        return f"{target} {args}".strip() or path.name
    except Exception:
        return path.name


def _cim_startup_names() -> set[str]:
    """Read-only cross-check via PowerShell CIM, for names the registry/
    folder scan might miss (e.g. unusual install locations)."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_StartupCommand | Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return {line.strip() for line in result.stdout.splitlines() if line.strip()}
    except Exception:
        return set()


def list_startup_items() -> list[StartupItem]:
    if not REGISTRY_AVAILABLE:
        return []

    items: list[StartupItem] = []
    seen_names: set[str] = set()

    for hive, subkey, source in _RUN_KEYS:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                i = 0
                while True:
                    try:
                        name, command, _type = winreg.EnumValue(key, i)
                    except OSError:
                        break
                    i += 1
                    approved = _read_approved(winreg.HKEY_CURRENT_USER, _APPROVED_RUN_KEY, name)
                    items.append(StartupItem(
                        name=name, command=str(command), source=source, kind="registry",
                        enabled=True if approved is None else approved,
                        hive=hive, subkey=subkey,
                    ))
                    seen_names.add(name.lower())
        except OSError:
            continue

    for folder, source in _startup_folders():
        if not folder.is_dir():
            continue
        for entry in sorted(folder.iterdir()):
            if entry.is_dir() or entry.name.lower() == "desktop.ini":
                continue
            approved = _read_approved(winreg.HKEY_CURRENT_USER, _APPROVED_FOLDER_KEY, entry.name)
            items.append(StartupItem(
                name=entry.stem, command=_resolve_shortcut_target(entry), source=source,
                kind="shortcut", enabled=True if approved is None else approved,
                path=entry,
            ))
            seen_names.add(entry.stem.lower())

    # Read-only extras CIM sees but the registry/folder scan didn't
    for name in _cim_startup_names():
        if name.lower() not in seen_names:
            items.append(StartupItem(
                name=name, command="(scheduled task or non-standard location)",
                source="Windows Startup List (info only)", kind="info", enabled=True,
            ))

    items.sort(key=lambda it: (not it.enabled, it.name.lower()))
    return items


def set_startup_enabled(item: StartupItem, enabled: bool) -> None:
    if item.kind == "info":
        raise NotImplementedError("This item isn't a registry/shortcut entry — manage it from the app it came from.")
    if item.kind == "registry":
        _write_approved(winreg.HKEY_CURRENT_USER, _APPROVED_RUN_KEY, item.name, enabled)
    else:
        _write_approved(winreg.HKEY_CURRENT_USER, _APPROVED_FOLDER_KEY, item.path.name, enabled)
    item.enabled = enabled


# -------------------------------------------------------------------- services

@dataclass
class ServiceItem:
    name: str
    display_name: str
    status: str        # "Running" | "Stopped" | "Paused" | ...
    start_type: str     # "Auto" | "Manual" | "Disabled" | "Boot" | "System"
    description: str = ""


_START_TYPE_MAP = {
    win32service.SERVICE_AUTO_START if PYWIN32_SERVICE_AVAILABLE else 2: "Auto",
    win32service.SERVICE_DEMAND_START if PYWIN32_SERVICE_AVAILABLE else 3: "Manual",
    win32service.SERVICE_DISABLED if PYWIN32_SERVICE_AVAILABLE else 4: "Disabled",
    win32service.SERVICE_BOOT_START if PYWIN32_SERVICE_AVAILABLE else 0: "Boot",
    win32service.SERVICE_SYSTEM_START if PYWIN32_SERVICE_AVAILABLE else 1: "System",
}

_SC_START_TYPE_ARG = {"Auto": "auto", "Manual": "demand", "Disabled": "disabled"}


def list_services() -> list[ServiceItem]:
    if not PYWIN32_SERVICE_AVAILABLE:
        return _list_services_via_sc()

    items: list[ServiceItem] = []
    scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ENUMERATE_SERVICE)
    try:
        for name, display_name, status_tuple in win32service.EnumServicesStatus(scm):
            try:
                cfg = win32serviceutil.QueryServiceConfig(name)
                start_type = _START_TYPE_MAP.get(cfg[1], "Unknown")
            except Exception:
                start_type = "Unknown"
            # EnumServicesStatus already returns SERVICE_STATUS; don't
            # QueryServiceStatus again per service (that doubled the scan).
            try:
                status_code = status_tuple[1]
            except Exception:
                status_code = 0
            status = {1: "Stopped", 4: "Running", 7: "Paused"}.get(status_code, "Unknown")
            items.append(ServiceItem(name=name, display_name=display_name,
                                      status=status, start_type=start_type))
    finally:
        win32service.CloseServiceHandle(scm)

    items.sort(key=lambda s: s.display_name.lower())
    return items


def _list_services_via_sc() -> list[ServiceItem]:
    """Fallback if pywin32 isn't installed: parse `sc query` + `sc qc`."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Service | Select-Object Name, DisplayName, Status, StartType | ConvertTo-Json"],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        raw = json.loads(result.stdout or "[]")
        if isinstance(raw, dict):
            raw = [raw]
        return [
            ServiceItem(name=s.get("Name", ""), display_name=s.get("DisplayName", s.get("Name", "")),
                        status=str(s.get("Status", "Unknown")), start_type=str(s.get("StartType", "Unknown")))
            for s in raw
        ]
    except Exception:
        return []


def set_service_start_type(service_name: str, start_type: str) -> None:
    """start_type: 'Auto' | 'Manual' | 'Disabled'. Requires admin —
    caller should check is_admin() first and prompt for elevation."""
    arg = _SC_START_TYPE_ARG.get(start_type)
    if arg is None:
        raise ValueError(f"Unsupported start type: {start_type}")
    result = subprocess.run(
        ["sc", "config", service_name, f"start={arg}"],
        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or result.stdout.strip() or "sc config failed")


def create_restore_point(description: str = "Startup Optimizer cleanup") -> None:
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f'Checkpoint-Computer -Description "{description}" -RestorePointType "MODIFY_SETTINGS"'],
        capture_output=True, text=True, timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
