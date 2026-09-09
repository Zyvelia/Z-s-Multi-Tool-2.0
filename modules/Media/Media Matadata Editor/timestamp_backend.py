"""CTk-free file timestamp helpers (os.utime + optional Windows creation time)."""

from __future__ import annotations

import datetime
import os
import time

DATE_FMT = "%Y-%m-%d %H:%M:%S"

try:
    import win32con
    import win32file
    import pywintypes
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False


def creation_editable() -> bool:
    return WIN32_AVAILABLE and os.name == "nt"


def creation_note() -> str:
    if not WIN32_AVAILABLE and os.name == "nt":
        return "pywin32 not installed — Created time is read-only. Run: pip install pywin32"
    if os.name != "nt":
        return "Created time editing is Windows-only on this platform."
    return "Format: YYYY-MM-DD HH:MM:SS"


def read_times(path: str) -> dict:
    st = os.stat(path)

    def fmt(ts):
        return datetime.datetime.fromtimestamp(ts).strftime(DATE_FMT)

    return {
        "Created": fmt(st.st_ctime),
        "Modified": fmt(st.st_mtime),
        "Accessed": fmt(st.st_atime),
    }


def parse(text: str) -> datetime.datetime:
    return datetime.datetime.strptime(text.strip(), DATE_FMT)


def write_times(path: str, modified_text: str, accessed_text: str, created_text: str | None = None) -> None:
    mtime = parse(modified_text)
    atime = parse(accessed_text)
    os.utime(path, (atime.timestamp(), mtime.timestamp()))
    if created_text and creation_editable():
        set_windows_creation_time(path, parse(created_text))


def set_windows_creation_time(path: str, dt: datetime.datetime) -> None:
    handle = win32file.CreateFile(
        path, win32con.GENERIC_WRITE, win32con.FILE_SHARE_WRITE, None,
        win32con.OPEN_EXISTING, win32con.FILE_ATTRIBUTE_NORMAL, None,
    )
    try:
        wintime = pywintypes.Time(time.mktime(dt.timetuple()))
        win32file.SetFileTime(handle, wintime, None, None)
    finally:
        handle.close()
