"""
utils.py — Shared utility helpers for Universal File Viewer.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import stat
import time
from pathlib import Path
from typing import Optional

from core import theme

# ── palette (matches app theme) ──────────────────────────
GOLD        = "#e6a817"
GREEN       = "#34d399"
TEAL        = "#2dd4bf"

_THEME_ALIASES = {
    "BG": "BG",
    "BG_PANEL": "PANEL",
    "BG_RAISED": "PANEL_2",
    "BORDER": "BORDER",
    "ACCENT": "ACCENT",
    "ACCENT_DIM": "ACCENT_DIM",
    "ACCENT_GLOW": "ACCENT_GLOW",
    "RED": "DANGER",
    "RED_DIM": "RED_DIM",
    "TEXT_HI": "TEXT",
    "TEXT_MID": "MUTED",
    "TEXT_LOW": "FAINT",
    "FONT": "FONT_FAMILY",
    "FONT_MONO": "MONO_FAMILY",
}


def __getattr__(name: str):
    key = _THEME_ALIASES.get(name)
    if key is not None:
        return getattr(theme, key)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ── file type groupings ───────────────────────────────────

TEXT_EXTENSIONS = {
    ".txt", ".log", ".json", ".xml", ".yaml", ".yml",
    ".ini", ".cfg", ".csv", ".md",
}

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".ico",
}

AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".aac", ".ogg",
}

ARCHIVE_EXTENSIONS = {
    ".zip", ".7z", ".tar", ".gz",
}


def detect_viewer(path: str | Path) -> str:
    """
    Return the viewer type string for a given file path.
    Returns one of: 'text', 'image', 'audio', 'archive', 'hex'
    """
    ext = Path(path).suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return "text"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    if ext in ARCHIVE_EXTENSIONS:
        return "archive"
    return "hex"


def human_size(n_bytes: int) -> str:
    """Convert byte count to human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n_bytes < 1024:
            return f"{n_bytes:.1f} {unit}"
        n_bytes /= 1024
    return f"{n_bytes:.1f} PB"


def file_hash(path: str | Path, algo: str = "sha256") -> str:
    """Compute hex digest of a file. algo: 'sha256' or 'md5'."""
    h = hashlib.new(algo)
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return "unavailable"


def file_permissions(path: str | Path) -> str:
    """Return rwx-style permission string."""
    try:
        mode = os.stat(path).st_mode
        return stat.filemode(mode)
    except OSError:
        return "unknown"


def mime_type(path: str | Path) -> str:
    """Return MIME type string."""
    mt, _ = mimetypes.guess_type(str(path))
    return mt or "application/octet-stream"


def format_ts(ts: float) -> str:
    """Format a Unix timestamp as a readable date string."""
    return time.strftime("%Y-%m-%d  %H:%M:%S", time.localtime(ts))


def safe_read_text(path: str | Path, max_bytes: int = 10 * 1024 * 1024) -> tuple[str, str]:
    """
    Try to read a file as UTF-8, fallback to latin-1.
    Returns (text, encoding_used).
    Raises ValueError if file exceeds max_bytes.
    """
    size = os.path.getsize(path)
    if size > max_bytes:
        raise ValueError(f"File too large ({human_size(size)}). Max {human_size(max_bytes)}.")
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read(), enc
        except (UnicodeDecodeError, LookupError):
            continue
    raise ValueError("Could not decode file as text.")


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))