import pygame
import pygame.mixer
import random
import os
import time
import threading
from array import array


# ---------------------------------------------------------------------------
# Pygame state constants – mirror the subset of vlc.State used in ui.py
# ---------------------------------------------------------------------------
class _State:
    NothingSpecial = 0
    Opening        = 1
    Buffering      = 2
    Playing        = 3
    Paused         = 4
    Stopped        = 5
    Ended          = 6
    Error          = 7


class State:
    """Drop-in replacement for the vlc.State namespace used by ui.py."""
    NothingSpecial = _State.NothingSpecial
    Opening        = _State.Opening
    Buffering      = _State.Buffering
    Playing        = _State.Playing
    Paused         = _State.Paused
    Stopped        = _State.Stopped
    Ended          = _State.Ended
    Error          = _State.Error



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


class PygameMusicEngine:
    """
    Drop-in replacement for VLCMusicEngine.

    Public interface is identical so that ui.py needs only a one-line
    import change (and the removal of vlc.State references).
    """

    def __init__(self):
        pygame.mixer.init()

        self.playlist    = []
        self.index       = -1
        self.db          = None   # set when a library queue is loaded via load_ids()

        self.shuffle     = False
        self.repeat_mode = "off"   # off | one | all

        self.volume      = 0.5
        self._apply_volume()

        # Internal state tracking
        self._state           = _State.Stopped
        self._paused          = False
        self._play_started_at = 0.0

        # Background polling thread — uses get_busy() only, no pygame
        # display or event system required, so works fine alongside tkinter.
        self._monitor_thread = threading.Thread(target=self._monitor_loop,
                                                 daemon=True)
        self._monitor_thread.start()

    # ── Private helpers ───────────────────────────────────────

    def _monitor_loop(self):
        """
        Polls pygame.mixer.music.get_busy() every 200 ms.
        When a track naturally finishes (not paused/stopped by the user),
        automatically advances to the next track — no pygame display or
        event system needed, so it works safely alongside tkinter.
        """
        while True:
            # Only act when we expected music to be playing but it stopped.
            # Give newly-started tracks a brief grace period: get_busy()
            # can momentarily report False right after play() is called
            # (file still loading/decoding), which would otherwise be
            # misread as "track ended" and cause an instant skip.
            if (self._state == _State.Playing
                    and not pygame.mixer.music.get_busy()
                    and (time.monotonic() - self._play_started_at) > 0.75):
                print("[DEBUG] Track ended detected by poll.")
                self._state = _State.Ended
                self.next()
            time.sleep(0.2)

    def _apply_volume(self):
        pygame.mixer.music.set_volume(self.volume)

    # ── Load ──────────────────────────────────────────────────

    def load(self, files):
        """Load an explicit, small list of file paths (e.g. 'Add Files')."""
        self.db       = None
        self.playlist = [os.path.abspath(f) for f in (files or [])]
        self.index    = 0 if self.playlist else -1
        self._state   = _State.Stopped
        self._paused  = False

    def load_ids(self, db, ids, start_index=0):
        """
        Load a (possibly huge, e.g. 750,000+) list of song IDs backed by a
        db.Library. Used for browsing/searching/shuffling the full library
        without ever materializing every file path in memory at once.
        """
        self.db       = db
        self.playlist = LazyPlaylist(db, ids)
        self.index    = start_index if len(self.playlist) else -1
        self._state   = _State.Stopped
        self._paused  = False

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

        self.index   = i
        self._paused = False

        path = self.playlist[i]
        if not os.path.exists(path):
            print("[Pygame] Missing file:", path)
            return

        pygame.mixer.music.stop()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        self._apply_volume()
        self._play_started_at = time.monotonic()
        self._state = _State.Playing
        print(f"[Pygame] Playing: {os.path.basename(path)} (Index: {i})")

    def pause(self):
        if self._state == _State.Playing:
            pygame.mixer.music.pause()
            self._paused = True
            self._state  = _State.Paused
        elif self._state == _State.Paused:
            # Toggle back to playing on second press
            pygame.mixer.music.unpause()
            self._paused = False
            self._state  = _State.Playing

    def stop(self):
        pygame.mixer.music.stop()
        self._state  = _State.Stopped
        self._paused = False

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
        print("[DEBUG] next() method called.")
        if not self.playlist:
            print("[DEBUG] next() - No playlist.")
            return

        if self.repeat_mode == "one":
            print("[DEBUG] next() - Repeat one, replaying current.")
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
            print(f"[DEBUG] next() - Shuffle, playing index {self.index}")
            self.play_at(self.index)
            return

        if self.index + 1 < len(self.playlist):
            print(f"[DEBUG] next() - Playing next in sequence: {self.index + 1}")
            self.play_at(self.index + 1)
        elif self.repeat_mode == "all":
            print("[DEBUG] next() - Repeat all, playing first song.")
            self.play_at(0)
        else:
            print("[DEBUG] next() - End of playlist, stopping.")
            self.stop()
            self.index = -1
            print("[Pygame] Playlist finished.")

    def prev(self):
        print("[DEBUG] prev() method called.")
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
            print("[Pygame] Playlist empty after removal.")

    # ── State ─────────────────────────────────────────────────

    def is_playing(self):
        return pygame.mixer.music.get_busy() and not self._paused

    def get_state(self):
        """
        Returns a State constant compatible with the vlc.State checks in ui.py.
        """
        if self._paused:
            return State.Paused
        if pygame.mixer.music.get_busy():
            return State.Playing
        if self._state == _State.Stopped:
            return State.Stopped
        if self._state == _State.Ended:
            return State.Ended
        return State.NothingSpecial

    def get_time(self):
        """Returns current playback position in seconds."""
        if not pygame.mixer.music.get_busy() and not self._paused:
            return 0
        pos_ms = pygame.mixer.music.get_pos()
        return max(0, pos_ms / 1000) if pos_ms >= 0 else 0

    def get_length(self):
        """
        Returns track length in seconds using mutagen if available,
        otherwise returns 0 (progress bar won't show, but playback still works).
        """
        if self.index < 0 or not self.playlist:
            return 0
        if isinstance(self.playlist, LazyPlaylist):
            meta = self.playlist.meta_at(self.index)
            if meta and meta.get("duration"):
                return meta["duration"]
            return 0
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
        """Releases pygame mixer resources."""
        pygame.mixer.music.stop()
        pygame.mixer.quit()
        print("[Pygame] Resources released.")


# ---------------------------------------------------------------------------
# Backwards-compat alias so existing code that does
#   from .player import VLCMusicEngine
# still works without any changes to ui.py's import line.
# ---------------------------------------------------------------------------
VLCMusicEngine = PygameMusicEngine