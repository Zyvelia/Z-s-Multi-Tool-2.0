"""
Update Manager — core logic.

Built entirely on first-party Windows tooling (sc.exe, reg.exe, PowerShell's
Get-HotFix and the Windows Update Agent COM API, wusa.exe) — nothing here
downloads or runs third-party code:

  1. Block / unblock Windows Update — sets the "Windows Update" service
     (wuauserv) and the "Update Orchestrator Service" (UsoSvc) to
     Disabled (blocked) or back to their default Manual start type
     (unblocked) via `sc config`, and stops/starts them to match. This
     is the same reversible mechanism as opening services.msc and
     changing the startup type by hand — nothing is deleted or patched.

  2. Pause updates for N days — a gentler alternative that leaves the
     services running but writes the same registry expiry Settings >
     Windows Update's own "Pause updates" toggle writes. Capped at 35
     days, same as the OS.

  3. List installed updates (Get-HotFix, enriched with real descriptions
     from Windows Update Agent history), show full update history
     (including failed/pending entries), and uninstall a specific update
     by KB number via wusa.exe /uninstall — the same command Control
     Panel's "Uninstall an update" runs under the hood.

Blocking, pausing, and uninstalling all require admin rights; see
admin.py. All subprocess calls run hidden (no flashing console window)
and with a timeout so a stuck command can't hang the worker thread
forever.
"""

from __future__ import annotations

import datetime
import json
import queue
import re
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Callable, List, Optional

IS_WINDOWS = __import__("os").name == "nt"

# Services involved in Windows Update. wuauserv is the core service;
# UsoSvc (Update Orchestrator) is what actually schedules/triggers scans
# on modern Windows 10/11 and needs to be blocked too or updates still
# get orchestrated in the background.
SERVICES = ["wuauserv", "UsoSvc"]

_CREATE_NO_WINDOW = 0x08000000


def _run(cmd: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    kwargs = dict(capture_output=True, text=True, timeout=timeout)
    if IS_WINDOWS:
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    return subprocess.run(cmd, **kwargs)


def _run_powershell(script: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return _run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        timeout=timeout,
    )


# ── Block / unblock ─────────────────────────────────────────────────────


@dataclass
class ServiceStatus:
    name: str
    start_type: str  # "disabled" | "demand" (manual) | "auto" | "unknown"
    running: bool


def _query_service(name: str) -> ServiceStatus:
    if not IS_WINDOWS:
        return ServiceStatus(name, "unknown", False)
    try:
        result = _run(["sc", "qc", name])
        start_type = "unknown"
        m = re.search(r"START_TYPE\s*:\s*\d\s+(\w+)", result.stdout)
        if m:
            token = m.group(1).upper()
            if "DISABLED" in token:
                start_type = "disabled"
            elif "DEMAND" in token:
                start_type = "demand"
            elif "AUTO" in token:
                start_type = "auto"

        state_result = _run(["sc", "query", name])
        running = bool(re.search(r"STATE\s*:\s*\d+\s+RUNNING", state_result.stdout))
        return ServiceStatus(name, start_type, running)
    except Exception:
        return ServiceStatus(name, "unknown", False)


def get_status() -> List[ServiceStatus]:
    """Current start type / running state of each Windows Update service."""
    return [_query_service(s) for s in SERVICES]


def is_blocked() -> bool:
    """True if every relevant service is disabled."""
    statuses = get_status()
    return bool(statuses) and all(s.start_type == "disabled" for s in statuses)


def block_updates() -> List[str]:
    """Disable and stop the Windows Update services. Returns a list of
    human-readable error strings (empty on full success). Requires admin."""
    errors: List[str] = []
    if not IS_WINDOWS:
        return ["Not running on Windows."]
    for name in SERVICES:
        try:
            _run(["sc", "stop", name])
        except Exception:
            pass  # OK if it wasn't running
        try:
            cfg = _run(["sc", "config", name, "start=", "disabled"])
            if cfg.returncode != 0:
                errors.append(f"{name}: {cfg.stderr.strip() or cfg.stdout.strip()}")
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    return errors


def unblock_updates() -> List[str]:
    """Restore the Windows Update services to their default Manual start
    type and start wuauserv. Returns a list of human-readable error
    strings (empty on full success). Requires admin."""
    errors: List[str] = []
    if not IS_WINDOWS:
        return ["Not running on Windows."]
    for name in SERVICES:
        try:
            cfg = _run(["sc", "config", name, "start=", "demand"])
            if cfg.returncode != 0:
                errors.append(f"{name}: {cfg.stderr.strip() or cfg.stdout.strip()}")
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    try:
        _run(["sc", "start", "wuauserv"])
    except Exception:
        pass  # Non-fatal — it's demand-start now and will start when needed
    return errors


# ── Pause updates (gentler alternative to fully disabling) ────────────────
#
# Windows itself has a "Pause updates" feature (Settings > Windows Update)
# that's less drastic than disabling the services outright: quality/driver
# updates are held off for a bounded window and then resume automatically
# (Windows caps this at 35 days, whatever N is requested), while the
# Update services stay enabled the whole time. It works by writing an
# expiry date to the same registry values the Settings app itself writes.
# Two locations are set for reliability: the UX key (what Settings reads
# back to show "Updates paused until <date>") and the policy keys (what
# the update agent itself enforces).

_PAUSE_UX_KEY = r"HKLM\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings"
_PAUSE_UX_VALUE = "PauseUpdatesExpiryTime"
_PAUSE_POLICY_KEY = r"HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate"
_PAUSE_POLICY_VALUES = ("PauseFeatureUpdatesStartTime", "PauseQualityUpdatesStartTime")

_MAX_PAUSE_DAYS = 35  # hard cap enforced by Windows itself


def _reg_set(key: str, value: str, data: str) -> bool:
    try:
        r = _run(["reg", "add", key, "/v", value, "/t", "REG_SZ", "/d", data, "/f"])
        return r.returncode == 0
    except Exception:
        return False


def _reg_delete(key: str, value: str) -> None:
    try:
        _run(["reg", "delete", key, "/v", value, "/f"])
    except Exception:
        pass  # fine if it didn't exist


def _reg_query(key: str, value: str) -> Optional[str]:
    try:
        r = _run(["reg", "query", key, "/v", value])
    except Exception:
        return None
    if r.returncode != 0:
        return None
    m = re.search(re.escape(value) + r"\s+REG_SZ\s+(.+)", r.stdout)
    return m.group(1).strip() if m else None


def pause_updates(days: int) -> List[str]:
    """Pause Windows Update for `days` (capped at 35, Windows' own limit).
    Requires admin (writes to HKLM). Returns a list of error strings."""
    errors: List[str] = []
    if not IS_WINDOWS:
        return ["Not running on Windows."]
    days = max(1, min(int(days), _MAX_PAUSE_DAYS))
    now = datetime.datetime.utcnow()
    start_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    expiry_str = (now + datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not _reg_set(_PAUSE_UX_KEY, _PAUSE_UX_VALUE, expiry_str):
        errors.append("Couldn't set the pause expiry (needs admin).")
    for value in _PAUSE_POLICY_VALUES:
        if not _reg_set(_PAUSE_POLICY_KEY, value, start_str):
            errors.append(f"Couldn't set {value} (needs admin).")
    return errors


def resume_updates_from_pause() -> List[str]:
    """Cancel an active pause early. Requires admin."""
    errors: List[str] = []
    if not IS_WINDOWS:
        return ["Not running on Windows."]
    _reg_delete(_PAUSE_UX_KEY, _PAUSE_UX_VALUE)
    for value in _PAUSE_POLICY_VALUES:
        _reg_delete(_PAUSE_POLICY_KEY, value)
    return errors


def get_pause_expiry() -> Optional[datetime.datetime]:
    """When the current pause ends, or None if updates aren't paused."""
    raw = _reg_query(_PAUSE_UX_KEY, _PAUSE_UX_VALUE)
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            expiry = datetime.datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue
    else:
        return None
    if expiry <= datetime.datetime.utcnow():
        return None  # stale value; Windows just hasn't cleaned it up yet
    return expiry


# ── Installed updates ────────────────────────────────────────────────────


@dataclass
class InstalledUpdate:
    kb_id: str          # e.g. "KB5031354"
    category: str       # short generic tag from Get-HotFix, e.g. "Security Update"
    title: str           # human-readable "what this is for", from Update Agent history
    installed_on: str


def _parse_ps_date(value: object) -> str:
    m = re.search(r"/Date\((\d+)\)/", str(value))
    if not m:
        return str(value or "")
    return datetime.datetime.fromtimestamp(int(m.group(1)) / 1000).strftime("%Y-%m-%d")


_RESULT_CODE_TEXT = {
    0: "Not started",
    1: "In progress",
    2: "Succeeded",
    3: "Succeeded with errors",
    4: "Failed",
    5: "Cancelled",
}


def _query_update_history_raw(limit: int = 300) -> List[dict]:
    """Raw rows from the Windows Update Agent's history
    (Microsoft.Update.Session / QueryHistory), newest-first. Doesn't
    require admin. Returns [] on any failure (COM can be finicky, e.g.
    under WOW64 PowerShell) rather than raising."""
    script = (
        "try {"
        " $s = New-Object -ComObject Microsoft.Update.Session;"
        " $q = $s.CreateUpdateSearcher();"
        f" $n = [Math]::Min($q.GetTotalHistoryCount(), {int(limit)});"
        " if ($n -gt 0) {"
        "   $q.QueryHistory(0, $n) | Where-Object { $_.Title } |"
        "   Select-Object Title, Description, Date, ResultCode |"
        "   ConvertTo-Json -Compress -Depth 3"
        " } else { '[]' }"
        "} catch { '[]' }"
    )
    try:
        result = _run_powershell(script, timeout=90)
    except Exception:
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    return data


def _get_update_history() -> dict:
    """Best-effort map of KB number -> descriptive title/description, built
    from _query_update_history_raw(). This is what actually explains *what
    an update is for* — Get-HotFix's Description field is almost always
    just a generic tag like "Security Update". Used to enrich the
    installed-updates list; see get_full_history() for the unfiltered feed.
    """
    history: dict = {}
    for row in _query_update_history_raw():
        title = str(row.get("Title") or "").strip()
        m = re.search(r"\(KB(\d+)\)", title)
        if not m:
            continue
        kb = f"KB{m.group(1)}"
        date = _parse_ps_date(row.get("Date"))
        succeeded = row.get("ResultCode") == 2
        entry = history.get(kb)
        # Prefer the most recent *succeeded* entry for a given KB; only
        # fall back to a non-succeeded one if we have nothing else yet.
        if entry is None or (succeeded and (date > entry["date"] or not entry["succeeded"])):
            history[kb] = {
                "title": title,
                "description": str(row.get("Description") or "").strip(),
                "date": date,
                "succeeded": succeeded,
            }
    return history


@dataclass
class HistoryEntry:
    title: str
    kb_id: str        # "" if this history row has no KB number (e.g. Defender defs)
    date: str
    result: str        # "Succeeded" | "Failed" | "Cancelled" | ...
    succeeded: bool


def get_full_history(limit: int = 300) -> List[HistoryEntry]:
    """Every Windows Update history entry (installs, failed attempts,
    definition updates, driver updates, etc.) — not just what's currently
    installed. Newest-first. Doesn't require admin."""
    entries = []
    for row in _query_update_history_raw(limit=limit):
        title = str(row.get("Title") or "").strip()
        if not title:
            continue
        m = re.search(r"\(KB(\d+)\)", title)
        kb = f"KB{m.group(1)}" if m else ""
        code = row.get("ResultCode")
        entries.append(
            HistoryEntry(
                title=title,
                kb_id=kb,
                date=_parse_ps_date(row.get("Date")),
                result=_RESULT_CODE_TEXT.get(code, "Unknown"),
                succeeded=(code == 2),
            )
        )
    entries.sort(key=lambda e: e.date, reverse=True)
    return entries


def list_installed_updates() -> List[InstalledUpdate]:
    """Installed updates, combining Get-HotFix (the authoritative "is this
    actually installed" list) with Update Agent history (which explains
    what each one is for). Doesn't require admin. Returns newest-first."""
    if not IS_WINDOWS:
        return []
    script = (
        "Get-HotFix | Select-Object HotFixID, Description, InstalledOn "
        "| ConvertTo-Json -Compress"
    )
    result = _run_powershell(script, timeout=60)
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]

    history = _get_update_history()

    updates = []
    for row in data:
        kb = str(row.get("HotFixID") or "").strip()
        if not kb:
            continue
        installed_on = _parse_ps_date(row.get("InstalledOn"))
        category = str(row.get("Description") or "").strip() or "Update"
        hist_entry = history.get(kb)
        if hist_entry:
            # Strip the trailing "(KBxxxxxxx)" from the title since we
            # already show the KB number separately in the UI.
            title = re.sub(r"\s*\(KB\d+\)\s*$", "", hist_entry["title"]).strip()
        else:
            title = ""  # unknown — UI falls back to "No description available"
        updates.append(
            InstalledUpdate(
                kb_id=kb,
                category=category,
                title=title,
                installed_on=installed_on,
            )
        )
    updates.sort(key=lambda u: u.installed_on, reverse=True)
    return updates


def kb_support_url(kb_id: str) -> str:
    """Official Microsoft support page for a KB article, for a "More info"
    link — lets the user read the full, authoritative description rather
    than relying on whatever we could scrape together locally."""
    number = kb_id.upper().lstrip("KB")
    return f"https://support.microsoft.com/help/{number}"


# ── Uninstall ─────────────────────────────────────────────────────────────


@dataclass
class ProgressEvent:
    kind: str  # "log" | "done" | "fatal_error"
    message: str = ""
    success: bool = False
    reboot_required: bool = False


# wusa.exe exit codes worth explaining to the user.
_WUSA_CODES = {
    0: ("success", False),
    3010: ("success", True),          # succeeded, reboot required
    2359302: ("already_uninstalled", False),
    87: ("not_found", False),         # invalid KB / not applicable
    1223: ("cancelled", False),       # user cancelled UAC/dialog
}


def _find_dism_package(kb_number: str) -> Optional[str]:
    """Look up the DISM component-store package name for an installed KB
    (e.g. "Package_for_KB5031592~31bf3856ad364e35~amd64~~19041.3320.1.1").
    Modern cumulative updates live here rather than as a standalone wusa
    package, which is why wusa.exe /uninstall reports exit code 87 for
    them. Returns None if no matching *installed* package is found."""
    script = (
        "try {"
        f"  Get-WindowsPackage -Online | Where-Object {{ $_.PackageName -match 'KB{kb_number}' -and $_.PackageState -eq 'Installed' }} |"
        "   Select-Object -First 1 -ExpandProperty PackageName"
        "} catch { '' }"
    )
    try:
        result = _run_powershell(script, timeout=60)
    except Exception:
        return None
    name = (result.stdout or "").strip()
    return name or None


def _dism_remove_package(package_name: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["DISM.exe", "/Online", "/Remove-Package", f"/PackageName:{package_name}", "/NoRestart"],
        capture_output=True,
        text=True,
        timeout=900,  # DISM package removal can genuinely take several minutes
        creationflags=_CREATE_NO_WINDOW,
    )


def uninstall_update(kb_id: str, out_queue: "queue.Queue[ProgressEvent]") -> None:
    """Uninstall a single update by KB number. Tries wusa.exe first (fast,
    works for standalone-package updates); if wusa reports the update
    isn't applicable that way — the common case for modern cumulative
    updates, which live in the DISM component store instead — falls back
    to `DISM /Remove-Package`. Meant to be run on a background thread;
    progress/result is pushed to out_queue. Requires admin — both tools
    fail with access-denied if not elevated."""
    kb_number = kb_id.upper().lstrip("KB")
    if not IS_WINDOWS:
        out_queue.put(ProgressEvent("fatal_error", "Not running on Windows."))
        return

    out_queue.put(ProgressEvent("log", f"Uninstalling KB{kb_number} via wusa…"))
    try:
        result = subprocess.run(
            ["wusa.exe", "/uninstall", f"/kb:{kb_number}", "/quiet", "/norestart"],
            capture_output=True,
            text=True,
            timeout=600,
            creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        out_queue.put(ProgressEvent("fatal_error", "Timed out waiting for wusa.exe."))
        return
    except Exception as exc:
        out_queue.put(ProgressEvent("fatal_error", f"Failed to launch wusa.exe: {exc}"))
        return

    code = result.returncode
    if code in (0, 3010):
        reboot = code == 3010
        msg = f"KB{kb_number} uninstalled." + (" A restart is required to finish." if reboot else "")
        out_queue.put(ProgressEvent("done", msg, success=True, reboot_required=reboot))
        return
    elif code == 2359302:
        out_queue.put(ProgressEvent("done", f"KB{kb_number} was already uninstalled.", success=True))
        return
    elif code != 87 and code != -2145116156:
        detail = (result.stderr or result.stdout or "").strip()
        out_queue.put(ProgressEvent(
            "done",
            f"KB{kb_number} uninstall failed (exit code {code})." + (f" {detail}" if detail else ""),
            success=False,
        ))
        return

    # wusa says "not applicable" — almost always means this is a modern
    # cumulative update sitting in the DISM component store rather than a
    # standalone package. Try DISM before giving up.
    out_queue.put(ProgressEvent(
        "log",
        f"wusa can't remove KB{kb_number} directly (likely a cumulative update) — "
        f"looking it up in the DISM component store…",
    ))
    package_name = _find_dism_package(kb_number)
    if not package_name:
        out_queue.put(ProgressEvent(
            "done",
            f"KB{kb_number} isn't a removable package — Windows has likely folded it "
            f"into a newer cumulative update, so it can no longer be uninstalled on its own.",
            success=False,
        ))
        return

    out_queue.put(ProgressEvent(
        "log", f"Found {package_name} — removing via DISM (this can take a few minutes)…"
    ))
    try:
        dism_result = _dism_remove_package(package_name)
    except subprocess.TimeoutExpired:
        out_queue.put(ProgressEvent("fatal_error", "Timed out waiting for DISM."))
        return
    except Exception as exc:
        out_queue.put(ProgressEvent("fatal_error", f"Failed to launch DISM: {exc}"))
        return

    dcode = dism_result.returncode
    if dcode in (0, 3010):
        out_queue.put(ProgressEvent(
            "done", f"KB{kb_number} removed via DISM. A restart is required to finish.",
            success=True, reboot_required=True,
        ))
    else:
        detail = (dism_result.stdout or dism_result.stderr or "").strip()
        # DISM's own output usually says why (e.g. package is not
        # "Removable" because something else now depends on it).
        tail = detail[-500:] if detail else ""
        out_queue.put(ProgressEvent(
            "done",
            f"KB{kb_number} couldn't be removed via DISM either (exit code {dcode})."
            + (f" {tail}" if tail else ""),
            success=False,
        ))


def uninstall_update_async(kb_id: str) -> "queue.Queue[ProgressEvent]":
    """Convenience wrapper: starts uninstall_update on a daemon thread and
    returns the queue the UI should poll."""
    q: "queue.Queue[ProgressEvent]" = queue.Queue()
    threading.Thread(target=uninstall_update, args=(kb_id, q), daemon=True).start()
    return q
