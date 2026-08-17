"""
module.py — Module descriptor for Universal File Viewer.
Holds module-level metadata and configuration constants.
"""

from __future__ import annotations

MODULE_NAME    = "Universal File Viewer"
MODULE_VERSION = "1.0.0"
MODULE_AUTHOR  = "Vault System"
MODULE_DESC    = (
    "View, edit, and manage any file — text, hex dump, "
    "images, audio, and archives — all in one place."
)
MODULE_ICON    = "📁"
MODULE_CATEGORY = "Tools"

# Maximum file size to attempt text opening (bytes)
TEXT_SIZE_LIMIT = 10 * 1024 * 1024   # 10 MB

# Max initial hex rows to render
HEX_INITIAL_ROWS = 512

# Supported extension sets (mirrored from utils for easy import)
TEXT_EXTS    = {".txt", ".log", ".json", ".xml", ".yaml", ".yml",
                ".ini", ".cfg", ".csv", ".md"}
IMAGE_EXTS   = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".ico"}
AUDIO_EXTS   = {".mp3", ".wav", ".flac", ".aac", ".ogg"}
ARCHIVE_EXTS = {".zip", ".7z", ".tar", ".gz"}
