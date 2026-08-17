"""
Startup Manager — core logic.

Lists everything Windows will launch at sign-in, from two sources:
  - Registry Run keys (HKCU/HKLM, plus the WOW6432Node mirror on 64-bit
    Windows for 32-bit apps)
  - Startup folder shortcuts (per-user and all-users)

Disabling an item does NOT delete it. It writes the same 12-byte
"StartupApproved" flag Windows' own Task Manager > Startup tab uses
(HKCU ...\\Explorer\\StartupApproved\\Run and \\StartupFolder), so:
  - the change is exactly what Task Manager would show/do
  - it's fully reversible from either app
  - it never requires admin rights, even for HKLM-sourced entries,
    because the approval flag always lives under HKCU

Permanently removing an item (deleting the Run value or the shortcut
file) is offered separately and is the only destructive action here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
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
except ImportError:  # pragma: no cover - pywin32 not installed
    win32com = None  # type: ignore
    WIN32COM_AVAILABLE = False


# Run keys we scan. (hive, subkey, label)
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
    kind: str  # "registry" | "shortcut"
    enabled: bool
    # Enough info to act on the item later without re-scanning:
    hive: int | None = None          # registry only
    subkey: str | None = None        # registry only
    path: Path | None = None         # shortcut only


def _read_approved(hive, subkey: str, value_name: str) -> bool | None:
    """Returns True/False if a StartupApproved flag exists for this name,
    or None if there's no flag at all (Windows treats "no flag" as
    enabled, since every startup item is enabled by default)."""
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
    """Best-effort .lnk target + arguments. Falls back to the filename
    alone if pywin32 isn't installed or the shortcut can't be parsed."""
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


def list_startup_items() -> list[StartupItem]:
    if not REGISTRY_AVAILABLE:
        return []

    items: list[StartupItem] = []

    # ---- Registry Run keys ----
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
        except OSError:
            continue  # key doesn't exist on this machine — fine

    # ---- Startup folder shortcuts ----
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

    items.sort(key=lambda it: (not it.enabled, it.name.lower()))
    return items


def set_enabled(item: StartupItem, enabled: bool) -> None:
    if item.kind == "registry":
        _write_approved(winreg.HKEY_CURRENT_USER, _APPROVED_RUN_KEY, item.name, enabled)
    else:
        _write_approved(winreg.HKEY_CURRENT_USER, _APPROVED_FOLDER_KEY, item.path.name, enabled)
    item.enabled = enabled


def remove_item(item: StartupItem) -> None:
    """Permanently removes the entry (deletes the Run value or the
    shortcut file). Unlike set_enabled(), this cannot be undone from
    within the app."""
    if item.kind == "registry":
        with winreg.OpenKey(item.hive, item.subkey, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, item.name)
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _APPROVED_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, item.name)
        except OSError:
            pass
    else:
        item.path.unlink(missing_ok=True)
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _APPROVED_FOLDER_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, item.path.name)
        except OSError:
            pass


def open_containing_folder(item: StartupItem) -> None:
    if item.kind == "shortcut" and item.path is not None:
        os.startfile(item.path.parent)  # type: ignore[attr-defined]
