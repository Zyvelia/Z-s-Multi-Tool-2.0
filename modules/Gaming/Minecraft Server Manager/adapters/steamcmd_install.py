"""SteamCMD install worker — downloads/updates dedicated server files."""

from __future__ import annotations

import platform
import queue
import re
import subprocess
import threading
from pathlib import Path

from ..core.events import DownloadEvent

_CREATE_NO_WINDOW = 0x08000000

_STEAMCMD_CANDIDATES = [
    Path(r"C:\steamcmd\steamcmd.exe"),
    Path(r"C:\Program Files (x86)\Steam\steamapps\common\SteamCMD\steamcmd.exe"),
    Path(r"D:\steamcmd\steamcmd.exe"),
    Path("steamcmd"),
]


def find_steamcmd() -> tuple[Path | None, str]:
    """Locate steamcmd.exe on this machine."""
    if platform.system() != "Windows":
        return Path("steamcmd"), ""

    for candidate in _STEAMCMD_CANDIDATES:
        if str(candidate) == "steamcmd":
            try:
                proc = subprocess.run(
                    ["where", "steamcmd"],
                    capture_output=True,
                    text=True,
                    creationflags=_CREATE_NO_WINDOW,
                    timeout=8,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    return Path(proc.stdout.strip().splitlines()[0]), ""
            except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
                continue
        elif candidate.exists():
            return candidate, ""
    return None, (
        "SteamCMD wasn't found. Install it from store.steampowered.com/about/ "
        "or place steamcmd.exe in C:\\steamcmd\\"
    )


_PROGRESS_RE = re.compile(r"Update state\s*\(\d+\)\s*.*?(\d+\.\d+)\s*:", re.I)


class SteamCmdInstallWorker(threading.Thread):
    """Runs `steamcmd +login anonymous +app_update <id> validate +quit`."""

    def __init__(self, server_dir: Path, app_id: str):
        super().__init__(daemon=True)
        self.server_dir = server_dir
        self.app_id = str(app_id).strip()
        self.events: queue.Queue[DownloadEvent] = queue.Queue()

    def run(self) -> None:
        try:
            self._run()
        except Exception as e:  # noqa: BLE001
            self.events.put(DownloadEvent(kind="error", message=str(e)))

    def _run(self) -> None:
        if not self.app_id.isdigit():
            self.events.put(DownloadEvent(kind="error", message="Steam App ID must be numeric."))
            return

        steamcmd, err = find_steamcmd()
        if steamcmd is None:
            self.events.put(DownloadEvent(kind="error", message=err))
            return

        self.server_dir.mkdir(parents=True, exist_ok=True)
        self.events.put(DownloadEvent(kind="progress", message="Starting SteamCMD…"))

        args = [
            str(steamcmd),
            "+@NoPromptForPassword", "1",
            "+force_install_dir", str(self.server_dir),
            "+login", "anonymous",
            "+app_update", self.app_id, "validate",
            "+quit",
        ]
        popen_kwargs: dict = dict(
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        if platform.system() == "Windows":
            popen_kwargs["creationflags"] = _CREATE_NO_WINDOW

        try:
            proc = subprocess.Popen(args, **popen_kwargs)
        except OSError as e:
            self.events.put(DownloadEvent(kind="error", message=f"Couldn't launch SteamCMD: {e}"))
            return

        assert proc.stdout is not None
        last_pct = 0.0
        for raw in proc.stdout:
            line = raw.rstrip("\r\n")
            if not line:
                continue
            self.events.put(DownloadEvent(kind="progress", message=line))
            m = _PROGRESS_RE.search(line)
            if m:
                pct = float(m.group(1))
                if pct >= last_pct:
                    last_pct = pct
                    self.events.put(DownloadEvent(
                        kind="progress",
                        downloaded=int(pct),
                        total=100,
                        message=f"SteamCMD updating… {pct:.0f}%",
                    ))

        code = proc.wait()
        if code != 0:
            self.events.put(DownloadEvent(
                kind="error",
                message=f"SteamCMD exited with code {code}. Check App ID and folder permissions.",
            ))
            return

        self.events.put(DownloadEvent(
            kind="done",
            message=f"SteamCMD finished — App ID {self.app_id} installed/updated.",
        ))
