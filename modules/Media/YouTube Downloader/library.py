# modules/yt_downloader/library.py
#
# The job list in web_server.py only remembers what's been downloaded
# since the app started — restart it and you can no longer see (or
# re-download to your phone) anything downloaded earlier. This scans the
# configured output folder directly so "Browse videos" always reflects
# what's actually on disk, including anything the channel watcher queued
# into its own "Watched - <channel>" subfolders.

from __future__ import annotations

import os

from . import metadata_tag

VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov"}
AUDIO_EXTS = {".mp3", ".m4a", ".opus"}
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS


def scan_library(output_dir, limit=500):
    """Returns [{"rel_path","name","folder","size","mtime","kind",
    "video_id","video_url"}, ...], newest file first. `rel_path` is
    relative to output_dir and is the only thing the file-serving endpoint
    accepts — the client never supplies an absolute path. `video_id` /
    `video_url` come from the hidden tag embedded at download time (see
    metadata_tag.py) and are None for files that predate that tag or
    aren't mp3/mp4."""
    if not output_dir or not os.path.isdir(output_dir):
        return []
    base = os.path.realpath(output_dir)
    out = []
    for root, _dirs, files in os.walk(base):
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in MEDIA_EXTS:
                continue
            full = os.path.join(root, fname)
            try:
                stat = os.stat(full)
            except OSError:
                continue
            rel = os.path.relpath(full, base)
            folder = os.path.dirname(rel)
            video_id = metadata_tag.read_video_id(full)
            out.append({
                "rel_path": rel.replace(os.sep, "/"),
                "name": fname,
                "folder": "" if folder in ("", ".") else folder.replace(os.sep, "/"),
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "kind": "video" if ext in VIDEO_EXTS else "audio",
                "video_id": video_id,
                "video_url": metadata_tag.video_url(video_id) if video_id else None,
            })
    out.sort(key=lambda f: f["mtime"], reverse=True)
    return out[:limit]


def ids_on_disk(output_dir):
    """The set of YouTube video ids already embedded in files on disk —
    used by the channel watcher so re-watching a channel (or watching one
    you'd already downloaded videos from manually) doesn't re-download
    what's already sitting in the output folder."""
    return {f["video_id"] for f in scan_library(output_dir, limit=100000) if f.get("video_id")}


def resolve_library_file(output_dir, rel_path):
    """Validates rel_path can't escape output_dir (no `..` traversal, no
    absolute path override) and returns the real absolute path, or None."""
    if not output_dir or not rel_path:
        return None
    base = os.path.realpath(output_dir)
    candidate = os.path.realpath(os.path.join(base, rel_path))
    if candidate != base and not candidate.startswith(base + os.sep):
        return None
    return candidate if os.path.isfile(candidate) else None
