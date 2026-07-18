# core/updater.py
#
# Self-updater backed by GitHub Releases.
#
# How it works:
#   1. check_for_update() hits the GitHub API for the latest release tag
#      and compares it against APP_VERSION.
#   2. If newer, apply_update() downloads the Inno Setup installer
#      attached to the release (the same Setup.exe that install.iss
#      produces — upload it as the release asset, not a raw app exe),
#      writes a tiny .bat "handoff script", launches it, then exits.
#      A running exe can't be replaced while it's in use on Windows, so
#      the .bat waits for this process to fully exit, then runs the
#      installer silently (/VERYSILENT, same AppId → in-place update,
#      not a second install) and relaunches the app from its installed
#      path once setup finishes.
#
# Wiring:
#   - Settings toggle -> "check on launch" (core/app.py calls
#     check_on_launch_async() if the user has this enabled)
#   - Settings "Check for Updates Now" button -> check_and_prompt()
#     (always works regardless of the toggle, since the user asked)

import os
import sys
import subprocess
import tempfile
import threading
from tkinter import messagebox

import requests
from packaging import version as _version

# ── Fill these in once the repo is public ────────────────────────────────
GITHUB_OWNER = "Zyvelia"   # e.g. "yourusername"
GITHUB_REPO = "https://github.com/Zyvelia/Z-s-Multi-Tool-2.0/tree/main"    # e.g. "Zs-Multi-Tool"

# Keep this in sync with APP_VERSION in pages/settings_page.py.
# Bump it (and tag a matching vX.Y.Z GitHub Release) each time you ship.
APP_VERSION = "2.6.0"


def _api_url() -> str:
    return f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


def is_configured() -> bool:
    """False until GITHUB_OWNER/GITHUB_REPO above are filled in."""
    return bool(GITHUB_OWNER and GITHUB_REPO)


def check_for_update():
    """
    Returns {"version": str, "url": str} if a newer GitHub Release exists,
    otherwise None. Never raises: any network/parsing failure is treated
    as "no update available" so this is always safe to call on launch.
    """
    if not is_configured():
        return None

    try:
        resp = requests.get(_api_url(), timeout=5)
        resp.raise_for_status()
        data = resp.json()

        latest = data.get("tag_name", "").lstrip("v")
        assets = data.get("assets", [])
        if not latest or not assets:
            return None

        # Expects the Inno Setup installer (install.iss output, e.g.
        # "ZsMultiToolSetup.exe") uploaded as the release asset — not a
        # raw portable exe. apply_update() runs whatever this points to
        # as an installer.
        installer_asset = next(
            (a for a in assets if a["name"].lower().endswith(".exe")),
            assets[0]
        )

        if _version.parse(latest) > _version.parse(APP_VERSION):
            return {"version": latest, "url": installer_asset["browser_download_url"]}
    except Exception as e:
        print(f"[updater] Update check failed: {e}")

    return None


def _download(url: str, dest_path: str):
    resp = requests.get(url, stream=True, timeout=30)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)


def apply_update(url: str):
    """
    Downloads the Inno Setup installer, writes + launches a handoff
    script, then exits this process so the installer can run against an
    exe that's no longer locked, and relaunch the app once it's done.
    """
    if not getattr(sys, "frozen", False):
        messagebox.showinfo(
            "Update",
            "Auto-update only applies to the built .exe — "
            "you're running from source right now."
        )
        return

    exe_path = sys.executable  # install dir doesn't change — same AppId, in-place update
    installer_path = os.path.join(tempfile.gettempdir(), "_update_setup.exe")
    bat_path = os.path.join(tempfile.gettempdir(), "_apply_update.bat")
    pid = os.getpid()

    try:
        _download(url, installer_path)
    except Exception as e:
        messagebox.showerror("Update Failed", f"Could not download update:\n{e}")
        return

    # Waits for this process (by PID) to actually exit before touching the
    # exe, rather than a fixed sleep — more reliable if shutdown is slow.
    # /VERYSILENT + matching AppId in install.iss makes this an in-place
    # update (registry/uninstall entries and shortcuts stay correct)
    # rather than a second parallel install.
    bat_script = f"""@echo off
:wait
tasklist /fi "PID eq {pid}" | find "{pid}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait
)
"{installer_path}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
start "" "{exe_path}"
del "{installer_path}"
del "%~f0"
"""
    with open(bat_path, "w") as f:
        f.write(bat_script)

    subprocess.Popen(
        ["cmd", "/c", bat_path],
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    sys.exit()


def _prompt_and_apply(update: dict):
    if messagebox.askyesno(
        "Update Available",
        f"Version {update['version']} is available "
        f"(you have {APP_VERSION}).\n\n"
        f"Update now? The app will restart automatically."
    ):
        apply_update(update["url"])


def check_and_prompt(silent_if_none: bool = False):
    """
    Synchronous check for the manual "Check for Updates Now" button.
    Call from the main thread — it shows dialogs directly.
    """
    update = check_for_update()
    if update is None:
        if silent_if_none:
            return
        if not is_configured():
            messagebox.showinfo(
                "Updates Not Configured",
                "GITHUB_OWNER/GITHUB_REPO haven't been set in core/updater.py yet."
            )
        else:
            messagebox.showinfo("Up to Date", "You're already on the latest version.")
        return

    _prompt_and_apply(update)


def check_on_launch_async(app, delay_ms: int = 1500):
    """
    Fire-and-forget background check for use on app startup. Runs the
    network check off the main thread so it never blocks the UI; if an
    update is found, hops back onto the Tk main thread via app.after()
    (Tk widgets/dialogs aren't safe to touch from a background thread)
    to show the confirm dialog.
    """
    def _worker():
        update = check_for_update()
        if update:
            app.after(0, lambda: _prompt_and_apply(update))

    threading.Timer(delay_ms / 1000, _worker).start()