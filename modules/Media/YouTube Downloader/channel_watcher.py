# modules/yt_downloader/channel_watcher.py
#
# "Watch this channel" — periodically polls a YouTube channel/playlist URL
# with yt-dlp's flat-playlist extraction (cheap: no video is touched, just
# the upload list) and queues anything new through the same YTWebServer job
# queue the manual downloader and the phone page already use. Modeled on
# the job-queue pattern in web_server.py: in-memory state backed by a JSON
# file, a daemon thread, no external scheduler needed.
#
# Data model — one dict per watched source, in a plain JSON list:
#   {
#     "id": "8-char hex",
#     "url": "https://www.youtube.com/@SomeChannel/videos",
#     "name": "SomeChannel",                # display name, editable
#     "interval_minutes": 60,
#     "format": "mp4", "type": "video", "quality": "192",
#     "added_at": 1234567890.0,
#     "last_checked": 0.0,
#     "last_error": "",
#     "known_ids": ["dQw4w9WgXcQ", ...],    # every upload id seen so far
#     "seeded": true,                       # False until the first check
#   }
#
# The first check after adding a channel records every video currently
# published as "known" but only actually queues the newest few — so
# watching an established channel with 500 videos doesn't try to download
# all 500. Every check after that queues *every* id not yet in known_ids.

from __future__ import annotations

import json
import os
import threading
import time
import uuid

from core import paths

from . import library

CHANNELS_FILE = paths.migrate_legacy_file(
    paths.data_path("yt_downloader", "watched_channels.json"),
    "modules", "yt_downloader", "watched_channels.json",
)

try:
    import yt_dlp as youtube_dl
except ImportError:
    try:
        import youtube_dl
    except ImportError:
        youtube_dl = None

DEFAULT_INTERVAL_MINUTES = 60
MAX_KNOWN_IDS = 500          # per channel, oldest trimmed off the front
INITIAL_BACKFILL = 3         # videos actually downloaded when first added
CHECK_LOOP_SECONDS = 60      # how often the loop wakes up to see what's due
FETCH_LIMIT = 25             # how many of the newest uploads to look at per check


def normalize_channel_url(url: str) -> str:
    """Bare channel/handle/user URLs get pointed at their Videos tab so the
    flat listing comes back newest-first without Shorts/Live mixed in.
    Playlist URLs and URLs that already name a tab are left alone."""
    url = (url or "").strip()
    if not url:
        return url
    if "list=" in url or "/videos" in url or "/streams" in url or "/shorts" in url:
        return url
    if "youtube.com/@" in url or "/channel/" in url or "/c/" in url or "/user/" in url:
        return url.rstrip("/") + "/videos"
    return url


def _sanitize(name: str) -> str:
    if youtube_dl is not None:
        try:
            return youtube_dl.utils.sanitize_filename(name, restricted=False)
        except Exception:
            pass
    cleaned = "".join(ch for ch in (name or "") if ch not in '<>:"/\\|?*').strip()
    return cleaned or "channel"


class ChannelWatcher:
    """Owns the watched-channel list and the background polling thread.

    `queue_fn(url, fmt, dl_type, quality, subdir)` is injected rather than
    imported so this module doesn't need to know about YTWebServer — it's
    expected to be `YTWebServer.queue_download` with the args reordered to
    put subdir last.
    """

    def __init__(self, queue_fn, get_output_dir=None):
        self._queue_fn = queue_fn
        self._get_output_dir = get_output_dir
        self._lock = threading.Lock()
        self._channels = self._load()
        self._thread = None
        self._stop = threading.Event()
        self.on_update = None  # optional callback(channel_dict) for the UI

    # ---- persistence ---------------------------------------------------

    @staticmethod
    def _load():
        try:
            if os.path.exists(CHANNELS_FILE):
                with open(CHANNELS_FILE, encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
        return []

    def _save(self):
        try:
            os.makedirs(os.path.dirname(CHANNELS_FILE), exist_ok=True)
            with open(CHANNELS_FILE, "w", encoding="utf-8") as fh:
                json.dump(self._channels, fh, indent=2)
        except Exception:
            pass

    # ---- lifecycle -------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.check_due()
            except Exception:
                pass
            self._stop.wait(CHECK_LOOP_SECONDS)

    # ---- CRUD ------------------------------------------------------

    def list_channels(self):
        with self._lock:
            return [self._public(c) for c in self._channels]

    @staticmethod
    def _public(c):
        return {
            "id": c["id"],
            "url": c["url"],
            "name": c.get("name") or c["url"],
            "interval_minutes": c.get("interval_minutes", DEFAULT_INTERVAL_MINUTES),
            "format": c.get("format", "mp4"),
            "type": c.get("type", "video"),
            "quality": c.get("quality", "192"),
            "added_at": c.get("added_at", 0),
            "last_checked": c.get("last_checked", 0),
            "last_error": c.get("last_error", ""),
            "downloaded_count": len(c.get("known_ids", [])),
        }

    def add_channel(self, url, name="", interval_minutes=None, fmt="mp4", dl_type="video", quality="192"):
        url = normalize_channel_url(url)
        if not url:
            return {"ok": False, "error": "missing url"}
        if fmt not in ("mp3", "mp4"):
            fmt = "mp4"
        if dl_type not in ("video", "playlist"):
            dl_type = "video"
        with self._lock:
            for c in self._channels:
                if c["url"] == url:
                    return {"ok": False, "error": "already watching that URL"}
            channel = {
                "id": uuid.uuid4().hex[:8],
                "url": url,
                "name": (name or "").strip(),
                "interval_minutes": int(interval_minutes or DEFAULT_INTERVAL_MINUTES),
                "format": fmt,
                "type": dl_type,
                "quality": str(quality),
                "added_at": time.time(),
                "last_checked": 0.0,
                "last_error": "",
                "known_ids": [],
                "seeded": False,
            }
            self._channels.append(channel)
            self._save()
        threading.Thread(target=self._check_one, args=(channel["id"],), daemon=True).start()
        return {"ok": True, "channel": self._public(channel)}

    def remove_channel(self, channel_id):
        with self._lock:
            before = len(self._channels)
            self._channels = [c for c in self._channels if c["id"] != channel_id]
            removed = len(self._channels) != before
            self._save()
        return {"ok": removed}

    def get_channel(self, channel_id):
        with self._lock:
            for c in self._channels:
                if c["id"] == channel_id:
                    return dict(c)
        return None

    # ---- checking ----------------------------------------------------

    def check_due(self):
        now = time.time()
        due = []
        with self._lock:
            for c in self._channels:
                interval = c.get("interval_minutes", DEFAULT_INTERVAL_MINUTES) * 60
                if now - c.get("last_checked", 0) >= interval:
                    due.append(c["id"])
        for cid in due:
            self._check_one(cid)

    def check_now(self, channel_id):
        if self.get_channel(channel_id) is None:
            return {"ok": False, "error": f"no watched channel {channel_id}"}
        threading.Thread(target=self._check_one, args=(channel_id,), daemon=True).start()
        return {"ok": True}

    def _fetch_entries(self, url, limit=FETCH_LIMIT):
        """Returns [{"id","url","title"}, ...] for the most recent `limit`
        uploads, newest first. Uses extract_flat so nothing is downloaded
        and no video page is even hit — just the channel/playlist listing."""
        if youtube_dl is None:
            raise RuntimeError("yt-dlp is not installed")
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "playlistend": limit,
            "skip_download": True,
        }
        with youtube_dl.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        entries = (info.get("entries") or [info]) if info else []
        out = []
        for e in entries:
            if not e:
                continue
            vid = e.get("id")
            link = e.get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else None)
            if vid and link:
                out.append({"id": vid, "url": link, "title": e.get("title") or vid})
        return out

    def _check_one(self, channel_id):
        channel = self.get_channel(channel_id)
        if channel is None:
            return
        try:
            entries = self._fetch_entries(channel["url"])
            known = set(channel.get("known_ids", []))
            if not channel.get("seeded") and self._get_output_dir:
                # Hidden ytdlid tags (metadata_tag.py) let us recognize
                # videos from this channel you already grabbed manually,
                # before this channel was ever watched, so they aren't
                # queued again.
                try:
                    known |= library.ids_on_disk(self._get_output_dir())
                except Exception:
                    pass
            new_entries = [e for e in entries if e["id"] not in known]
            to_download = new_entries[:INITIAL_BACKFILL] if not channel.get("seeded") else new_entries

            subdir = _sanitize("Watched - " + (channel.get("name") or channel["url"]))
            for e in reversed(to_download):  # oldest-of-the-new first
                try:
                    self._queue_fn(e["url"], channel.get("format", "mp4"),
                                   channel.get("type", "video"), channel.get("quality", "192"),
                                   subdir)
                except Exception:
                    pass

            all_ids = list(known.union(e["id"] for e in entries))
            updated = None
            with self._lock:
                for c in self._channels:
                    if c["id"] == channel_id:
                        c["known_ids"] = all_ids[-MAX_KNOWN_IDS:]
                        c["last_checked"] = time.time()
                        c["last_error"] = ""
                        c["seeded"] = True
                        updated = dict(c)
                        break
                self._save()
            if updated and self.on_update:
                try:
                    self.on_update(self._public(updated))
                except Exception:
                    pass
        except Exception as e:
            updated = None
            with self._lock:
                for c in self._channels:
                    if c["id"] == channel_id:
                        c["last_checked"] = time.time()
                        c["last_error"] = str(e)
                        updated = dict(c)
                        break
                self._save()
            if updated and self.on_update:
                try:
                    self.on_update(self._public(updated))
                except Exception:
                    pass
