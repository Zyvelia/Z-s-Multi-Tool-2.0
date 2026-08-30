"""yt-dlp bootstrap helper for the Game Server Manager."""
from __future__ import annotations
import os
import platform
import subprocess
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

YTDLP_DOWNLOAD_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"


def ytdlp_path() -> Path:
    try:
        from core import paths  # type: ignore
        return Path(paths.data_path("tools", "yt-dlp.exe"))
    except ImportError:  # pragma: no cover
        return Path(os.environ.get("APPDATA", Path.home())) / "ZsMultiTool" / "tools" / "yt-dlp.exe"


def _valid(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 100_000
    except OSError:
        return False


def ensure_ytdlp(*, timeout: int = 120) -> Path | None:
    """Download yt-dlp once when it is missing or invalid."""
    if platform.system() != "Windows":
        return None
    target = ytdlp_path()
    if _valid(target):
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="yt-dlp-", suffix=".exe", dir=target.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        req = Request(YTDLP_DOWNLOAD_URL, headers={"User-Agent": "ZsMultiTool/GameServerManager"})
        with urlopen(req, timeout=timeout) as response, temp.open("wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        if not _valid(temp):
            return None
        temp.replace(target)
        return target
    except Exception:
        return None
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def get_ytdlp_version(path: Path | None = None) -> str | None:
    exe = path or ytdlp_path()
    if not _valid(exe):
        return None
    try:
        kwargs = {"capture_output": True, "text": True, "timeout": 10}
        if platform.system() == "Windows":
            kwargs["creationflags"] = 0x08000000
        result = subprocess.run([str(exe), "--version"], **kwargs)
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None
