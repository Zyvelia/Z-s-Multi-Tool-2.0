# modules/yt_downloader/metadata_tag.py
#
# Every file this app has ever produced (see e.g. an old download's ID3
# tags) carries a hidden `ytdlid` field with the source video's YouTube id
# — invisible in a normal "Title / Artist" view, but enough to always trace
# a file back to where it came from, dedupe against, or reconstruct a
# youtube.com/watch?v=... link from a bare mp3/mp4 that's been renamed.
#
# This module re-implements that same tag so the channel watcher and the
# manual downloader both keep writing it:
#   - MP3  -> ID3 TXXX frame, desc="ytdlid"
#   - MP4/M4A -> the standard "freeform" iTunes atom, mean=com.apple.iTunes,
#     name=ytdlid (the same style QuickTime/iTunes uses for anything
#     without a dedicated atom, e.g. MusicBrainz ids)
#
# Silently a no-op (returns False) if mutagen isn't installed or the file
# type isn't one of the two above — never blocks a download over this.

from __future__ import annotations

import os

try:
    import mutagen  # noqa: F401
    _MUTAGEN_OK = True
except ImportError:
    _MUTAGEN_OK = False

_FREEFORM_MEAN = "com.apple.iTunes"
_FREEFORM_NAME = "ytdlid"


def embed_video_id(path: str, video_id: str) -> bool:
    """Writes the hidden ytdlid tag into `path`. Returns True on success."""
    if not (_MUTAGEN_OK and path and video_id and os.path.isfile(path)):
        return False
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".mp3":
            return _embed_mp3(path, video_id)
        if ext in (".m4a", ".mp4", ".m4v"):
            return _embed_mp4(path, video_id)
    except Exception:
        return False
    return False


def read_video_id(path: str) -> str | None:
    """Reads the hidden ytdlid tag back out of `path`, or None if it's not
    tagged (e.g. a file downloaded before this feature existed) or isn't a
    format this module tags."""
    if not (_MUTAGEN_OK and path and os.path.isfile(path)):
        return None
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".mp3":
            return _read_mp3(path)
        if ext in (".m4a", ".mp4", ".m4v"):
            return _read_mp4(path)
    except Exception:
        return None
    return None


def video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


# ---- MP3 (ID3 TXXX) -------------------------------------------------

def _embed_mp3(path, video_id):
    from mutagen.id3 import ID3, ID3NoHeaderError, TXXX
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.delall("TXXX:ytdlid")
    tags.add(TXXX(encoding=3, desc="ytdlid", text=[video_id]))
    tags.save(path)
    return True


def _read_mp3(path):
    from mutagen.id3 import ID3
    tags = ID3(path)
    frame = tags.get("TXXX:ytdlid")
    if frame and frame.text:
        return str(frame.text[0]) or None
    return None


# ---- MP4/M4A (freeform iTunes atom) ---------------------------------

def _embed_mp4(path, video_id):
    from mutagen.mp4 import MP4
    tags = MP4(path)
    key = f"----:{_FREEFORM_MEAN}:{_FREEFORM_NAME}"
    tags[key] = [video_id.encode("utf-8")]
    tags.save()
    return True


def _read_mp4(path):
    from mutagen.mp4 import MP4
    tags = MP4(path)
    key = f"----:{_FREEFORM_MEAN}:{_FREEFORM_NAME}"
    values = tags.get(key)
    if not values:
        return None
    value = values[0]
    return value.decode("utf-8") if isinstance(value, (bytes, bytearray)) else str(value)
