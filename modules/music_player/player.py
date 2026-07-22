import vlc
import random
import os
import time
import threading
import shutil
import subprocess
import tempfile
import hashlib
from array import array


# ---------------------------------------------------------------------------
# State — re-export libVLC's own State enum so ui.py's
# `from .player import VLCMusicEngine, State` and its `State.Paused` /
# `State.Ended` checks keep working unchanged. libVLC's State enum already
# has exactly the members (NothingSpecial/Opening/Buffering/Playing/Paused/
# Stopped/Ended/Error) the old pygame-based engine hand-rolled to mimic.
# ---------------------------------------------------------------------------
State = vlc.State


# ---------------------------------------------------------------------------
# ffmpeg transcode fallback
#
# libVLC natively decodes far more formats than SDL_mixer (pygame's old
# backend) did — MP3/FLAC/OGG/Opus/WMA/APE/AC3/DTS/etc. all play directly.
# The remaining gap is mostly tracker/module formats (.mod/.s3m/.it/.xm)
# and MIDI, which need a real synth VLC doesn't reliably provide out of
# the box. We keep the same ffmpeg pre-transcode path from the old engine
# for those, plus as a one-time retry if native VLC playback errors out on
# something unexpected. Transcoded copies are cached on disk (keyed by
# path + mtime) so a track is only ever transcoded once.
# ---------------------------------------------------------------------------

_FFMPEG_PATH = shutil.which("ffmpeg")
_TRANSCODE_CACHE_DIR = os.path.join(tempfile.gettempdir(), "musicplayer_transcode_cache")
_TRANSCODE_CACHE_LIMIT = 600  # max cached wav files before pruning oldest
                              # (raised from 300 now that cue-sheet tracks
                              # each cache their own short segment)

# Formats kept on the "always transcode" list even with VLC as the engine —
# tracker/module formats and MIDI, which need a real synth VLC doesn't
# reliably provide out of the box. Everything else that used to be on this
# list (wma/ape/wv/tta/dsf/dff/amr/ac3/dts/spx/voc/au/webm/3gp/m4b/...) is
# now handled natively by libVLC, so it's been dropped from this list.
_ALWAYS_TRANSCODE_EXTS = {
    ".mid", ".midi", ".xm", ".mod", ".s3m", ".it",
}


def _cache_path_for(path, start=None, end=None):
    key = f"{os.path.abspath(path)}|{start}|{end}"
    h = hashlib.sha1(key.encode("utf-8", "ignore")).hexdigest()
    return os.path.join(_TRANSCODE_CACHE_DIR, h + ".wav")


def _prune_transcode_cache():
    try:
        entries = [os.path.join(_TRANSCODE_CACHE_DIR, f)
                   for f in os.listdir(_TRANSCODE_CACHE_DIR)]
        if len(entries) <= _TRANSCODE_CACHE_LIMIT:
            return
        entries.sort(key=lambda p: os.path.getmtime(p))
        for p in entries[:len(entries) - _TRANSCODE_CACHE_LIMIT]:
            try:
                os.remove(p)
            except OSError:
                pass
    except OSError:
        pass


def _transcode_to_wav(path, start=None, end=None):
    """
    Decode `path` to a cached PCM WAV via ffmpeg, optionally extracting
    just the [start, end) segment in seconds (used for cue-sheet tracks —
    `end=None` means "to end of file"). Returns the cached wav path, or
    None if ffmpeg isn't available or the transcode failed.
    """
    if not _FFMPEG_PATH:
        return None
    try:
        os.makedirs(_TRANSCODE_CACHE_DIR, exist_ok=True)
        out_path = _cache_path_for(path, start, end)
        if os.path.exists(out_path) and os.path.getmtime(out_path) >= os.path.getmtime(path):
            return out_path

        cmd = [_FFMPEG_PATH, "-y"]
        if start:
            cmd += ["-ss", str(start)]
        cmd += ["-i", path]
        if end is not None:
            duration = max(0.05, end - (start or 0))
            cmd += ["-t", str(duration)]
        cmd += ["-vn", "-ar", "44100", "-ac", "2", out_path]

        subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=180, check=True,
        )
        if os.path.exists(out_path):
            _prune_transcode_cache()
            return out_path
    except Exception as e:
        print(f"[VLC] ffmpeg transcode failed for {path} "
              f"[{start}:{end}]: {e}")
    return None


class LazyPlaylist:
    """
    A sequence-like view over a (potentially huge) list of song IDs backed
    by a db.Library. Behaves like a list of file paths — len(), indexing,
    iteration, os.path.basename(playlist[i]) — so the rest of the engine
    and the UI don't need to know the difference. It never holds more than
    a small cache of resolved paths/tags in memory, so it's safe to load
    the entire 750,000+ song library as a single "playlist".
    """

    def __init__(self, db, ids):
        self.db = db
        self.ids = ids if isinstance(ids, array) else array('q', ids)
        self._path_cache = {}
        self._meta_cache = {}
        self._cache_order = []

    def __len__(self):
        return len(self.ids)

    def __bool__(self):
        return len(self.ids) > 0

    def _touch(self, i):
        self._cache_order.append(i)
        if len(self._cache_order) > 512:
            old = self._cache_order.pop(0)
            self._path_cache.pop(old, None)
            self._meta_cache.pop(old, None)

    def __getitem__(self, i):
        if isinstance(i, slice):
            return [self[j] for j in range(*i.indices(len(self)))]
        if i < 0:
            i += len(self)
        if i in self._path_cache:
            return self._path_cache[i]
        path = self.db.get_path(self.ids[i])
        self._path_cache[i] = path
        self._touch(i)
        return path

    def __iter__(self):
        for i in range(len(self)):
            yield self[i]

    def id_at(self, i):
        if i < 0:
            i += len(self)
        return self.ids[i]

    def meta_at(self, i):
        """Returns the DB row (title/artist/album/duration/path) for index i."""
        if i < 0:
            i += len(self)
        if i in self._meta_cache:
            return self._meta_cache[i]
        song = self.db.get_song(self.ids[i])
        self._meta_cache[i] = song
        self._touch(i)
        return song


class VLCMusicEngine:
    """
    Music playback engine built on libVLC (via python-vlc), replacing the
    previous pygame.mixer-based engine.

    Why: pygame is a compiled C extension tied to a specific Python build,
    and it lags behind (sometimes for months) on supporting new Python
    releases. python-vlc is a ctypes wrapper around libvlc.dll — nothing
    to rebuild per Python version — so it isn't exposed to that problem at
    all, on this Python version or any future one. It also means the
    music player and Media Center module now share the same underlying
    engine instead of running two separate audio stacks.

    Public interface is identical to the old engine so ui.py, mini_widget.py,
    and web_server.py all keep working unchanged.
    """

    def __init__(self):
        # --no-video: these are audio files, never open a video output.
        # --quiet: keep libVLC's own logging off stdout (it's chatty).
        self.instance = vlc.Instance("--no-video", "--quiet")
        self.player   = self.instance.media_player_new()

        self.playlist    = []
        self.index       = -1
        self.db          = None   # set when a library queue is loaded via load_ids()

        self.shuffle     = False
        self.repeat_mode = "off"   # off | one | all

        self.volume      = 0.5
        self._apply_volume()

        # Tracks the file + cue window currently loaded, so a failed
        # native playback attempt can be retried once through ffmpeg
        # without the caller needing to pass anything back in.
        self._current_path = None
        self._cue_start = None
        self._cue_end = None
        self._retry_done = False
        # Guards the Ended/Error poll below from firing more than once
        # per playback attempt (reset every time a new attempt starts).
        self._ended_handled = True

        # Background polling thread — mirrors the old engine's design so
        # behavior around the UI stays as close as possible to before.
        # libVLC's own State.Ended is reliable and immediate (no "busy
        # flag lagging by one poll" heuristics needed like SDL_mixer
        # required).
        self._monitor_thread = threading.Thread(target=self._monitor_loop,
                                                 daemon=True)
        self._monitor_thread.start()

    # ── Private helpers ───────────────────────────────────────

    def _monitor_loop(self):
        """
        Polls the VLC player's own state every 200 ms. Advances to the
        next track when a track ends naturally, and retries once via
        ffmpeg if native playback errors out (mirrors the old engine's
        error-recovery path).
        """
        while True:
            try:
                state = self.player.get_state()
                if state == vlc.State.Ended and not self._ended_handled:
                    self._ended_handled = True
                    print("[VLC] Track ended detected by poll.")
                    self.next()
                elif state == vlc.State.Error and not self._ended_handled:
                    self._ended_handled = True
                    self._retry_with_transcode()
            except Exception as e:
                print(f"[VLC] Monitor loop error: {e}")
            time.sleep(0.2)

    def _apply_volume(self):
        # libVLC volume is an int 0-100; our public API stays 0.0-1.0 to
        # match the old engine (ui.py and web_server.py both use 0.0-1.0).
        self.player.audio_set_volume(int(round(self.volume * 100)))

    def _start_media(self, path, cue_start, cue_end, force_transcode=False):
        """Builds a vlc.Media for `path` and starts playback."""
        self._current_path = path
        self._cue_start = cue_start
        self._cue_end = cue_end

        if force_transcode:
            transcoded = _transcode_to_wav(path, cue_start, cue_end)
            if not transcoded:
                print(f"[VLC] Could not transcode (is ffmpeg installed?): {path}")
                return
            media = self.instance.media_new(transcoded)
        else:
            media = self.instance.media_new(path)
            # libVLC supports playing just a slice of a file directly —
            # used for cue-sheet tracks that share one underlying audio
            # file (album.ape + album.cue). No pre-extraction needed.
            if cue_start is not None:
                media.add_option(f":start-time={cue_start}")
            if cue_end is not None:
                media.add_option(f":stop-time={cue_end}")

        self._ended_handled = False
        self.player.set_media(media)
        self.player.play()
        self._apply_volume()
        print(f"[VLC] Playing: {os.path.basename(path)} (Index: {self.index})")

    def _retry_with_transcode(self):
        """
        Called once from the monitor loop when native VLC playback errors
        out on a file it couldn't handle — retries the same track through
        the ffmpeg fallback. If the retry also fails, gives up and skips
        to the next track rather than looping forever.
        """
        if self._retry_done:
            print(f"[VLC] Retry also failed for "
                  f"{os.path.basename(self._current_path or '')}; skipping.")
            self.next()
            return
        self._retry_done = True
        print(f"[VLC] Native playback failed for "
              f"{os.path.basename(self._current_path or '')}; retrying via ffmpeg.")
        self._start_media(self._current_path, self._cue_start, self._cue_end,
                           force_transcode=True)

    # ── Load ──────────────────────────────────────────────────

    def load(self, files):
        """Load an explicit, small list of file paths (e.g. 'Add Files')."""
        self.db       = None
        self.playlist = [os.path.abspath(f) for f in (files or [])]
        self.index    = 0 if self.playlist else -1

    def load_ids(self, db, ids, start_index=0):
        """
        Load a (possibly huge, e.g. 750,000+) list of song IDs backed by a
        db.Library. Used for browsing/searching/shuffling the full library
        without ever materializing every file path in memory at once.
        """
        self.db       = db
        self.playlist = LazyPlaylist(db, ids)
        self.index    = start_index if len(self.playlist) else -1

    # ── Playback ──────────────────────────────────────────────

    def play(self):
        if not self.playlist:
            return
        if self.index < 0:
            self.index = 0
        self.play_at(self.index)

    def play_at(self, i):
        if not self.playlist or not (0 <= i < len(self.playlist)):
            return

        self.index      = i
        self._retry_done = False

        path = self.playlist[i]
        if not os.path.exists(path):
            print("[VLC] Missing file:", path)
            return

        # Cue-sheet tracks (album.ape + album.cue) share one underlying
        # audio file — `path` here is already that real file (LazyPlaylist
        # resolves it via db.get_path), so we just need to know which
        # slice of it this track covers.
        cue_start = cue_end = None
        if isinstance(self.playlist, LazyPlaylist):
            meta = self.playlist.meta_at(i)
            if meta:
                cue_start = meta.get("cue_start")
                cue_end = meta.get("cue_end")

        self.player.stop()

        ext = os.path.splitext(path)[1].lower()
        self._start_media(path, cue_start, cue_end,
                           force_transcode=(ext in _ALWAYS_TRANSCODE_EXTS))

    def pause(self):
        # libvlc_media_player_pause() toggles play/pause on its own —
        # matches the old engine's toggle-on-second-press behavior.
        self.player.pause()

    def stop(self):
        self.player.stop()

    # ── Volume ────────────────────────────────────────────────

    def set_volume(self, value):
        try:
            value = float(value)
        except Exception:
            value = 0.5
        self.volume = max(0.0, min(1.0, value))
        self._apply_volume()

    # ── Navigation ────────────────────────────────────────────

    def next(self):
        if not self.playlist:
            return

        if self.repeat_mode == "one":
            self.play_at(self.index)
            return

        if self.shuffle:
            if len(self.playlist) > 1:
                new_index = self.index
                while new_index == self.index:
                    new_index = random.randint(0, len(self.playlist) - 1)
                self.index = new_index
            else:
                self.index = 0
            self.play_at(self.index)
            return

        if self.index + 1 < len(self.playlist):
            self.play_at(self.index + 1)
        elif self.repeat_mode == "all":
            self.play_at(0)
        else:
            self.stop()
            self.index = -1
            print("[VLC] Playlist finished.")

    def prev(self):
        if not self.playlist:
            return

        if self.shuffle:
            if len(self.playlist) > 1:
                new_index = self.index
                while new_index == self.index:
                    new_index = random.randint(0, len(self.playlist) - 1)
                self.index = new_index
            else:
                self.index = 0
            self.play_at(self.index)
            return

        if self.index - 1 >= 0:
            self.play_at(self.index - 1)
        elif self.repeat_mode == "all":
            self.play_at(len(self.playlist) - 1)
        else:
            self.play_at(self.index)

    # ── Playlist Management ───────────────────────────────────

    def remove_track(self, index):
        if isinstance(self.playlist, LazyPlaylist):
            # Removing one song from a library-backed queue isn't a
            # meaningful operation here — use the search box instead.
            return
        if not (0 <= index < len(self.playlist)):
            return

        del self.playlist[index]

        if self.index > index:
            self.index -= 1
        elif self.index == index:
            self.stop()
            if not self.playlist:
                self.index = -1
            elif self.index >= len(self.playlist):
                self.index = len(self.playlist) - 1
                if self.index >= 0:
                    self.play_at(self.index)
            else:
                self.play_at(self.index)

        if not self.playlist:
            self.stop()
            self.index = -1
            print("[VLC] Playlist empty after removal.")

    # ── State ─────────────────────────────────────────────────

    def is_playing(self):
        return self.player.get_state() == vlc.State.Playing

    def get_state(self):
        """Returns a vlc.State value — same enum ui.py already checks against."""
        return self.player.get_state()

    def get_time(self):
        """Returns current playback position in seconds."""
        ms = self.player.get_time()
        return max(0, ms / 1000) if ms and ms >= 0 else 0

    def get_length(self):
        """
        Returns track length in seconds. Prefers the DB-stored duration
        (LazyPlaylist queues) or VLC's own parsed length, and falls back
        to mutagen if neither is available yet (e.g. right as a track
        starts, before libVLC has finished parsing it).
        """
        if self.index < 0 or not self.playlist:
            return 0
        if isinstance(self.playlist, LazyPlaylist):
            meta = self.playlist.meta_at(self.index)
            if meta and meta.get("duration"):
                return meta["duration"]

        length_ms = self.player.get_length()
        if length_ms and length_ms > 0:
            return length_ms / 1000

        path = self.playlist[self.index]
        try:
            from mutagen import File as MutagenFile
            audio = MutagenFile(path)
            if audio and audio.info:
                return audio.info.length
        except Exception:
            pass
        return 0

    def get_current_meta(self):
        """
        Returns the DB row (title/artist/album/duration/path) for the
        currently loaded track, or None if not applicable (e.g. an ad-hoc
        file list rather than a library queue). Lets the UI show proper
        tag-based titles without re-reading the file over the network.
        """
        if self.index < 0 or not self.playlist:
            return None
        if isinstance(self.playlist, LazyPlaylist):
            return self.playlist.meta_at(self.index)
        return None

    def release(self):
        """Releases the VLC player and instance."""
        try:
            self.player.stop()
        except Exception:
            pass
        try:
            self.player.release()
        except Exception:
            pass
        try:
            self.instance.release()
        except Exception:
            pass
        print("[VLC] Resources released.")


# ---------------------------------------------------------------------------
# Backwards-compat alias, in case anything still references the old name.
# ---------------------------------------------------------------------------
PygameMusicEngine = VLCMusicEngine
