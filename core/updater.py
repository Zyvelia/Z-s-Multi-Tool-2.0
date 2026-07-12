# core/updater.py
#
# Self-updater backed by GitHub Releases.
#
# How it works:
#   1. check_for_update() hits the GitHub API for the latest release tag
#      and compares it against APP_VERSION.
#   2. If newer, apply_update() downloads the released .exe next to the
#      currently running one, writes a tiny .bat "swap script", launches
#      it, then exits — a running exe can't overwrite itself on Windows,
#      so the .bat waits for this process to fully exit, deletes the old
#      exe, renames the new one into place, and relaunches it.
#
# Wiring:
#   - Settings toggle -> "check on launch" (core/app.py calls
#     check_on_launch_async() if the user has this enabled)
#   - Settings "Check for Updates Now" button -> check_and_prompt()
#     (always works regardless of the toggle, since the user asked)

import os
import sys
import subprocess
import threading
from tkinter import messagebox

import requests
from packaging import version as _version

# ── Fill these in once the repo is public ────────────────────────────────
GITHUB_OWNER = ""   # e.g. "yourusername"
GITHUB_REPO = ""    # e.g. "Zs-Multi-Tool"

# Keep this in sync with APP_VERSION in pages/settings_page.py.
# Bump it (and tag a matching vX.Y.Z GitHub Release) each time you ship.
APP_VERSION = "1.0.0"


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

        exe_asset = next(
            (a for a in assets if a["name"].lower().endswith(".exe")),
            assets[0]
        )

        if _version.parse(latest) > _version.parse(APP_VERSION):
            return {"version": latest, "url": exe_asset["browser_download_url"]}
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
    Downloads the new exe, writes + launches a swap script, then exits
    this process so the script can replace the (now-unlocked) exe and
    relaunch it.
    """
    if not getattr(sys, "frozen", False):
        messagebox.showinfo(
            "Update",
            "Auto-update only applies to the built .exe — "
            "you're running from source right now."
        )
        return

    exe_path = sys.executable
    exe_dir = os.path.dirname(exe_path)
    new_exe = os.path.join(exe_dir, "_update_download.exe")
    bat_path = os.path.join(exe_dir, "_apply_update.bat")
    pid = os.getpid()

    try:
        _download(url, new_exe)
    except Exception as e:
        messagebox.showerror("Update Failed", f"Could not download update:\n{e}")
        return

    # Waits for this process (by PID) to actually exit before touching the
    # exe, rather than a fixed sleep — more reliable if shutdown is slow.
    bat_script = f"""@echo off
:wait
tasklist /fi "PID eq {pid}" | find "{pid}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait
)
del "{exe_path}"
move /y "{new_exe}" "{exe_path}"
start "" "{exe_path}"
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
