# CTk-free VLC video engine. Shared by the classic VideoPlayerPage and the Qt tab.
import os
import random
import time
import urllib.parse

import vlc


def is_url(s: str) -> bool:
    try:
        return urllib.parse.urlparse(s).scheme in ("http", "https")
    except Exception:
        return False


def url_display_name(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    name = os.path.basename(parsed.path.rstrip("/"))
    if not name:
        name = parsed.netloc or url
    return urllib.parse.unquote(name)


class VLCMediaEngine:

    def __init__(self):
        self.instance = vlc.Instance()
        self.player = self.instance.media_player_new()
        self.playlist = []
        self.index = -1
        self.shuffle = False
        self.repeat_mode = "off"
        self.volume = 0.5
        self._apply_volume()

    def load(self, files):
        self.playlist = [f if is_url(f) else os.path.abspath(f) for f in (files or [])]
        self.index = 0 if self.playlist else -1

    def add_track(self, mrl):
        mrl = mrl if is_url(mrl) else os.path.abspath(mrl)
        self.playlist.append(mrl)
        if self.index < 0:
            self.index = 0
        return len(self.playlist) - 1

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
        if not is_url(path) and not os.path.exists(path):
            print("[VLC] Missing file:", path)
            return
        media = self.instance.media_new(path)
        self.player.set_media(media)
        self.player.play()
        time.sleep(0.05)
        self._apply_volume()

    def pause(self):
        self.player.pause()

    def stop(self):
        self.player.stop()

    def set_volume(self, value):
        try:
            value = float(value)
        except Exception:
            value = 0.5
        self.volume = max(0.0, min(1.0, value))
        self._apply_volume()

    def _apply_volume(self):
        self.player.audio_set_volume(int(self.volume * 100))

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

    def is_playing(self):
        return self.player.is_playing() == 1

    def get_state(self):
        return self.player.get_state()

    def get_time(self):
        return max(0, self.player.get_time() / 1000)

    def get_length(self):
        length = self.player.get_length()
        return max(0, length / 1000 if length else 0)

    def seek(self, seconds):
        try:
            self.player.set_time(int(max(0, seconds) * 1000))
        except Exception:
            pass
