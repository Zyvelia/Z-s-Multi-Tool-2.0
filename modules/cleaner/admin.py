"""
admin.py
--------
Windows UAC elevation helpers for the Cleaner module. Self-contained (no
dependency on core/ internals) so it works whether the app is run from
source or as a frozen PyInstaller exe.

Only the Cleaner module needs admin rights (to clear C:\\WINDOWS\\Temp,
Prefetch-type system folders, etc.) — this deliberately does NOT touch
the app manifest or force elevation on every launch, since your other
modules (tray, network auditor, etc.) don't need it. Elevation here is
on-demand: the user clicks "Restart as Administrator" only if/when a
scan or delete actually hits a permissions wall.
"""

from __future__ import annotations

import ctypes
import os
import sys


def is_admin() -> bool:
    """True if the current process is running elevated. Always False on
    non-Windows (there's nothing to elevate to)."""
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """Re-launch the current process elevated via the UAC prompt.

    Returns True if the elevated relaunch was *requested* successfully
    (the UAC prompt was shown) — the caller should then exit the current,
    non-elevated process. Returns False if the user cancelled the UAC
    prompt or elevation isn't possible (e.g. not on Windows).

    Handles both "python your_app.py" (dev) and a frozen PyInstaller exe
    (sys.frozen), since sys.executable points at the exe itself in the
    frozen case and at python.exe in the dev case.
    """
    if os.name != "nt":
        return False

    try:
        if getattr(sys, "frozen", False):
            # Frozen exe: sys.executable *is* the app.
            executable = sys.executable
            params = " ".join(f'"{a}"' for a in sys.argv[1:])
        else:
            # Running from source: relaunch python.exe with the script path.
            executable = sys.executable
            params = " ".join(f'"{a}"' for a in sys.argv)

        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", executable, params, None, 1
        )
        # ShellExecuteW returns a value > 32 on success; <= 32 means the
        # user cancelled the UAC prompt or it otherwise failed.
        return result > 32
    except Exception:
        return False
