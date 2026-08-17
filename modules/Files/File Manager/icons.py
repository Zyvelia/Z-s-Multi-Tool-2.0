"""
icons.py — Centralised icon/emoji map for Universal File Viewer.
All UI icons are defined here so they can be swapped easily.
"""

# Toolbar
ICON_OPEN       = "📂"
ICON_SAVE       = "💾"
ICON_SAVE_AS    = "📄"
ICON_FIND       = "🔍"
ICON_REPLACE    = "🔄"
ICON_REFRESH    = "↺"
ICON_SETTINGS   = "⚙"
ICON_CLOSE      = "✕"

# File types
ICON_TEXT       = "📝"
ICON_JSON       = "{ }"
ICON_XML        = "</>"
ICON_CSV        = "📊"
ICON_MD         = "Ⓜ"
ICON_IMAGE      = "🖼"
ICON_AUDIO      = "🎵"
ICON_HEX        = "🔢"
ICON_ARCHIVE    = "🗜"
ICON_BINARY     = "⬛"
ICON_FOLDER     = "📁"
ICON_FILE       = "📄"
ICON_UNKNOWN    = "❓"

# Audio controls
ICON_PLAY       = "▶"
ICON_PAUSE      = "⏸"
ICON_STOP       = "⏹"
ICON_VOLUME     = "🔊"
ICON_MUTE       = "🔇"

# Image controls
ICON_ZOOM_IN    = "🔍+"
ICON_ZOOM_OUT   = "🔍−"
ICON_FIT        = "⛶"
ICON_ROTATE_L   = "↺"
ICON_ROTATE_R   = "↻"
ICON_FLIP_H     = "↔"
ICON_FLIP_V     = "↕"

# Editor
ICON_UNDO       = "↩"
ICON_REDO       = "↪"
ICON_WRAP       = "↵"
ICON_READONLY   = "🔒"
ICON_LINENUM    = "#"

# Status
ICON_OK         = "✔"
ICON_ERROR      = "✖"
ICON_WARN       = "⚠"
ICON_INFO       = "ℹ"


def file_icon(ext: str) -> str:
    """Return the appropriate icon for a given file extension."""
    ext = ext.lower().lstrip(".")
    mapping = {
        # text
        "txt": ICON_TEXT, "log": ICON_TEXT, "md": ICON_MD,
        "ini": ICON_TEXT, "cfg": ICON_TEXT,
        # structured text
        "json": ICON_JSON, "xml": ICON_XML, "yaml": ICON_TEXT,
        "yml": ICON_TEXT, "csv": ICON_CSV,
        # image
        "png": ICON_IMAGE, "jpg": ICON_IMAGE, "jpeg": ICON_IMAGE,
        "bmp": ICON_IMAGE, "gif": ICON_IMAGE, "webp": ICON_IMAGE,
        "ico": ICON_IMAGE,
        # audio
        "mp3": ICON_AUDIO, "wav": ICON_AUDIO, "flac": ICON_AUDIO,
        "aac": ICON_AUDIO, "ogg": ICON_AUDIO,
        # archive
        "zip": ICON_ARCHIVE, "7z": ICON_ARCHIVE, "tar": ICON_ARCHIVE,
        "gz": ICON_ARCHIVE,
    }
    return mapping.get(ext, ICON_BINARY)
