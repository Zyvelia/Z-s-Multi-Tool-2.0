"""Hide console windows for child processes on Windows.

A --windowed PyInstaller exe has no console. When it starts a console
subsystem program (tailscale, adb, nmap, ffmpeg, pip, yt-dlp) without
CREATE_NO_WINDOW and with stdin inherited, Windows allocates a new
console for the child — a terminal flashes when you open a module.

Patching subprocess.Popen covers run/check_output/Popen in one place.
GUI children (explorer, scrcpy, Windows Terminal, games) are unaffected:
CREATE_NO_WINDOW only suppresses a console, not a windowed app.
Pass CREATE_NEW_CONSOLE if a caller really wants a visible terminal.
"""

from __future__ import annotations

import subprocess
import sys

_installed = False


def hidden_kwargs() -> dict:
    """Extra kwargs for a one-off subprocess call that must not flash."""
    kwargs = {"stdin": subprocess.DEVNULL}
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def install() -> None:
    global _installed
    if _installed or sys.platform != "win32":
        return

    orig = subprocess.Popen
    new_console = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010)

    class HiddenPopen(orig):
        def __init__(self, *args, **kwargs):
            flags = kwargs.get("creationflags") or 0
            if not (flags & new_console):
                kwargs["creationflags"] = flags | subprocess.CREATE_NO_WINDOW
                if "startupinfo" not in kwargs:
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = 0
                    kwargs["startupinfo"] = startupinfo
                if kwargs.get("stdin") is None:
                    kwargs["stdin"] = subprocess.DEVNULL
            super().__init__(*args, **kwargs)

    subprocess.Popen = HiddenPopen
    _installed = True
