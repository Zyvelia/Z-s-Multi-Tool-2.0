import vlc
import random
import os
import time



class VLCMediaEngine:

    def __init__(self):
        self.instance = vlc.Instance() # This is now correctly set to vlc.Instance()
        self.player = self.instance.media_player_new()

        self.playlist = []
        self.index = -1

        self.shuffle = False
        self.repeat_mode = "off"  # off | one | all

        self.volume = 0.5
        self._apply_volume()

    # ── Load ──────────────────────────────────────────────────

    def load(self, files):
        self.playlist = [os.path.abspath(f) for f in (files or [])]
        self.index = 0 if self.playlist else -1

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

        self.index = i
        self.player.stop()

        path = self.playlist[i]
        if not os.path.exists(path):
            print("[VLC] Missing file:", path)
            return

        media = self.instance.media_new(path)
        self.player.set_media(media)
        self.player.play()
        time.sleep(0.05)
        self._apply_volume()
        print("[VLC] Playing:", path)

    def pause(self):
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

    def _apply_volume(self):
        self.player.audio_set_volume(int(self.volume * 100))

    # ── Navigation ────────────────────────────────────────────

    def next(self):
        if not self.playlist:
            return

        if self.repeat_mode == "one":
            self.play_at(self.index)
            return

        if self.shuffle:
            self.index = random.randint(0, len(self.playlist) - 1)
            self.play_at(self.index)
            return

        if self.index + 1 < len(self.playlist):
            self.play_at(self.index + 1)
        elif self.repeat_mode == "all":
            self.play_at(0)
        else:
            self.stop()
            self.index = -1

    def prev(self):
        if not self.playlist:
            return

        if self.shuffle:
            self.index = random.randint(0, len(self.playlist) - 1)
            self.play_at(self.index)
            return

        if self.index - 1 >= 0:
            self.play_at(self.index - 1)
        elif self.repeat_mode == "all":
            self.play_at(len(self.playlist) - 1)

    # ── Playlist Management ───────────────────────────────────

    def remove_track(self, index):
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
                self.play_at(self.index)
            else:
                self.play_at(self.index)

        if not self.playlist:
            self.stop()
            self.index = -1

    # ── State ─────────────────────────────────────────────────

    def is_playing(self):
        return self.player.is_playing() == 1

    def get_state(self):
        return self.player.get_state()

    def get_time(self):
        return max(0, self.player.get_time() / 1000)

    def get_length(self):
        length = self.player.get_length()
        return max(0, length / 1000 if length else 0)
