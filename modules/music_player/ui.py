import customtkinter as ctk
from tkinter import filedialog
import os

from mutagen import File as MutagenFile

from .player import VLCMusicEngine, State
from core import theme

BG      = theme.BG
PANEL   = theme.PANEL
PANEL_2 = theme.PANEL_2
ACCENT  = theme.ACCENT
DANGER  = theme.DANGER
TEXT    = theme.TEXT
MUTED   = theme.MUTED

_BTN = dict(fg_color=PANEL_2, hover_color=ACCENT, text_color=TEXT,
            height=34, corner_radius=8)
_BTN_ACCENT = dict(fg_color=ACCENT, hover_color=theme.ACCENT_DIM, text_color="white",
                   height=34, corner_radius=8)


def _make_btn(parent, text, cmd, **overrides):
    kw = {**_BTN, **overrides}
    return ctk.CTkButton(parent, text=text, command=cmd, **kw)


class MusicPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=BG)

        self.manager = manager
        self.engine = getattr(manager, "music_engine", None) or VLCMusicEngine()
        manager.music_engine = self.engine

        self.song_buttons = []
        self.active_index = -1
        self._loop_running = False
        self._discord_rpc_active = False # NEW: Flag to track RPC status

        self._build_ui()
        self._sync_initial_state()
        self._start_loop()

    # ── Build ─────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()
        self._build_playlist_panel()
        self._build_now_playing()
        self._build_controls()

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        header.pack(fill="x", padx=12, pady=(12, 4))

        ctk.CTkLabel(
            header, text="🎵  Music Player",
            font=("Segoe UI", 22, "bold"), text_color=TEXT
        ).pack(side="left", padx=14, pady=10)

        self.status = ctk.CTkLabel(header, text="Idle", text_color=MUTED)
        self.status.pack(side="right", padx=14)

    def _build_playlist_panel(self):
        panel = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        panel.pack(fill="both", expand=True, padx=12, pady=6)

        # Header row
        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 0))

        ctk.CTkLabel(top, text="Playlist",
                     font=("Segoe UI", 15, "bold"), text_color=TEXT).pack(side="left")

        self.playlist_stats = ctk.CTkLabel(top, text="0 songs", text_color=MUTED)
        self.playlist_stats.pack(side="right")

        # Load buttons row
        load_row = ctk.CTkFrame(panel, fg_color="transparent")
        load_row.pack(fill="x", padx=10, pady=(6, 4))

        _make_btn(load_row, "＋ Add Files", self.load_files,
                  **_BTN_ACCENT).pack(side="left", padx=(0, 6))
        _make_btn(load_row, "📁 Load Folder", self.load_folder_playlist
                  ).pack(side="left")

        # Search
        self.search_entry = ctk.CTkEntry(
            panel, placeholder_text="Search playlist…", corner_radius=8)
        self.search_entry.pack(fill="x", padx=10, pady=(0, 6))
        self.search_entry.bind("<KeyRelease>", lambda e: self._filter_playlist())

        # Song list
        self.song_buttons_frame = ctk.CTkScrollableFrame(
            panel, fg_color=PANEL_2, corner_radius=8)
        self.song_buttons_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _build_now_playing(self):
        card = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        card.pack(fill="x", padx=12, pady=6)

        ctk.CTkLabel(card, text="Now Playing",
                     font=("Segoe UI", 12, "bold"), text_color=MUTED
                     ).pack(anchor="w", padx=14, pady=(10, 0))

        self.current_song_label = ctk.CTkLabel(
            card, text="Nothing playing", text_color=TEXT,
            font=("Segoe UI", 13), anchor="w")
        self.current_song_label.pack(fill="x", padx=14, pady=(2, 0))

        self.time_label = ctk.CTkLabel(card, text="00:00 / 00:00", text_color=MUTED)
        self.time_label.pack(anchor="w", padx=14, pady=(2, 4))

        self.progress = ctk.CTkProgressBar(
            card, progress_color=ACCENT, fg_color=PANEL_2, corner_radius=4)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=14, pady=(0, 12))

    def _build_controls(self):
        outer = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        outer.pack(fill="x", padx=12, pady=(4, 12))

        # Transport row
        transport = ctk.CTkFrame(outer, fg_color="transparent")
        transport.pack(pady=(10, 4))

        for col, (text, cmd) in enumerate([
            ("⏮", self.prev), ("▶", self.play),
            ("⏸", self.pause), ("⏭", self.next),
        ]):
            _make_btn(transport, text, cmd, width=56).grid(
                row=0, column=col, padx=4)

        # Mode row
        mode_row = ctk.CTkFrame(outer, fg_color="transparent")
        mode_row.pack(pady=(0, 4))

        self.shuffle_btn = _make_btn(mode_row, "🔀  Shuffle", self.toggle_shuffle, width=130)
        self.shuffle_btn.grid(row=0, column=0, padx=6)

        self.repeat_btn = _make_btn(mode_row, "🔁  Repeat", self.toggle_repeat, width=130)
        self.repeat_btn.grid(row=0, column=1, padx=6)

        # Volume row
        vol_row = ctk.CTkFrame(outer, fg_color="transparent")
        vol_row.pack(fill="x", padx=14, pady=(4, 12))

        ctk.CTkLabel(vol_row, text="Vol", text_color=MUTED,
                     font=("Segoe UI", 11)).pack(side="left", padx=(0, 8))

        self.volume = ctk.CTkSlider(
            vol_row, from_=0, to=1, progress_color=ACCENT,
            command=self.set_volume, corner_radius=4)
        self.volume.pack(side="left", fill="x", expand=True)

    # ── Initial State Sync ────────────────────────────────────

    def _sync_initial_state(self):
        vol = getattr(self.engine, "volume", 0.5)
        self.volume.set(vol)
        self.engine.set_volume(vol)

        # Update initial shuffle/repeat button states
        if self.engine.shuffle:
            self.shuffle_btn.configure(text="🔀  Shuffle", fg_color=ACCENT)

        mode = self.engine.repeat_mode
        if mode == "all":
            self.repeat_btn.configure(text="🔁  Repeat All", fg_color=ACCENT)
        elif mode == "one":
            self.repeat_btn.configure(text="🔂  Repeat One", fg_color="#2ecc71")

        # Initial UI state update
        self._update_playback_ui_state()


    # ── Loop ─────────────────────────────────────────────────

    def _start_loop(self):
        if not self._loop_running:
            self._loop_running = True
            self.after(300, self._update_loop)

    def _update_loop(self):
        if not self._loop_running:
            return

        current = max(0, self.engine.get_time())
        total   = max(0, self.engine.get_length())

        # Update now playing time and progress bar
        if total > 0:
            self.progress.set(current / total)
            self.time_label.configure(
                text=f"{int(current//60):02d}:{int(current%60):02d} / "
                     f"{int(total//60):02d}:{int(total%60):02d}")
        else:
            self.progress.set(0)
            self.time_label.configure(text="00:00 / 00:00")

        # Call the new unified UI state updater
        self._update_playback_ui_state()

        self.after(300, self._update_loop)

    # ── Load Files ────────────────────────────────────────────

    def load_files(self):
        files = filedialog.askopenfilenames(
            filetypes=[("Audio Files", "*.mp3 *.wav *.flac *.ogg *.m4a")])
        if files:
            self._load_playlist(list(files))
            self.status.configure(text="Files loaded")

    def load_folder_playlist(self):
        folder = filedialog.askdirectory()
        if not folder:
            return

        ext = (".mp3", ".wav", ".flac", ".ogg", ".m4a")
        files = sorted(
            os.path.join(root, f)
            for root, _dirs, filenames in os.walk(folder)
            for f in filenames
            if f.lower().endswith(ext)
        )

        if not files:
            self.status.configure(text="No audio files found")
            return

        self._load_playlist(files)
        self.status.configure(text=f"Folder loaded ({len(files)} songs)")

    # ── Playlist Core ─────────────────────────────────────────

    def _load_playlist(self, files):
        self.engine.load(files)
        self.playlist_stats.configure(
            text=f"{len(files)} {'song' if len(files) == 1 else 'songs'}")

        for w in self.song_buttons_frame.winfo_children():
            w.destroy()

        self.song_buttons.clear()
        # Active index is set in _update_playback_ui_state later

        for i, f in enumerate(files):
            name = os.path.basename(f)

            row = ctk.CTkFrame(self.song_buttons_frame, fg_color=PANEL, corner_radius=6)
            row.pack(fill="x", padx=4, pady=2)

            btn = ctk.CTkButton(
                row, text=f"{i + 1}.  {name}",
                fg_color=PANEL, hover_color=ACCENT, text_color=TEXT,
                anchor="w", height=30, corner_radius=6,
                command=lambda idx=i: self.play_song(idx))
            btn.pack(side="left", fill="x", expand=True)

            ctk.CTkButton(
                row, text="✕", width=32, height=30,
                fg_color="transparent", hover_color=DANGER,
                text_color=MUTED, corner_radius=6,
                command=lambda idx=i: self.remove_song(idx)
            ).pack(side="right", padx=2)

            self.song_buttons.append(btn)

        self._filter_playlist()
        self._update_playback_ui_state() # Update UI after loading new playlist

    def _filter_playlist(self):
        search = self.search_entry.get().lower()

        for i, row_widget in enumerate(self.song_buttons_frame.winfo_children()):
            if i < len(self.engine.playlist): # Ensure index is valid for current playlist
                # Get the actual song path from engine.playlist, as it's the source of truth
                song_path = self.engine.playlist[i]
                name = os.path.basename(song_path).lower()

                if search in name:
                    row_widget.pack(fill="x", padx=4, pady=2)
                else:
                    row_widget.pack_forget()
            else:
                row_widget.pack_forget()


    # ── Playback ─────────────────────────────────────────────

    def play_song(self, index):
        self.engine.play_at(index)
        self._update_playback_ui_state() # Update UI after explicit play

    def play(self):
        self.engine.play()
        self._update_playback_ui_state() # Update UI after explicit play

    def pause(self):
        self.engine.pause()
        self._update_playback_ui_state() # Update UI after explicit pause

    def next(self):
        self.engine.next()
        self._update_playback_ui_state() # Update UI after explicit next

    def prev(self):
        self.engine.prev()
        self._update_playback_ui_state() # Update UI after explicit prev

    def set_volume(self, value):
        self.engine.set_volume(value)

    # ── Shuffle / Repeat ──────────────────────────────────────

    def toggle_shuffle(self):
        self.engine.shuffle = not self.engine.shuffle
        if self.engine.shuffle:
            self.shuffle_btn.configure(text="🔀  Shuffle", fg_color=ACCENT)
        else:
            self.shuffle_btn.configure(text="🔀  Shuffle", fg_color=PANEL_2)

    def toggle_repeat(self):
        modes = ["off", "all", "one"]
        next_mode = modes[(modes.index(self.engine.repeat_mode) + 1) % len(modes)]
        self.engine.repeat_mode = next_mode

        if next_mode == "off":
            self.repeat_btn.configure(text="🔁  Repeat", fg_color=PANEL_2)
        elif next_mode == "all":
            self.repeat_btn.configure(text="🔁  Repeat All", fg_color=ACCENT)
        else:
            self.repeat_btn.configure(text="🔂  Repeat One", fg_color="#2ecc71")

    # ── Remove Song ───────────────────────────────────────────

    def remove_song(self, index):
        self.engine.remove_track(index)
        self._load_playlist(self.engine.playlist) # Reload playlist to update buttons
        self.status.configure(text="Removed") # Status will be overridden by _update_playback_ui_state soon
        self._update_playback_ui_state() # Ensure UI reflects new state

    # ── Highlight ─────────────────────────────────────────────

    def _highlight_active(self):
        for i, btn in enumerate(self.song_buttons):
            if i == self.active_index:
                btn.configure(fg_color=ACCENT, text_color="white")
            else:
                original_fg_color = PANEL
                # Check if the song's row is currently visible due to search filter
                if self.engine.playlist and i < len(self.engine.playlist):
                    song_path = self.engine.playlist[i]
                    search = self.search_entry.get().lower()
                    if search in os.path.basename(song_path).lower():
                        btn.configure(fg_color=original_fg_color, text_color=TEXT)
                    # Else, if not in search, it's packed_forget, no need to configure its color
                else: # Fallback if playlist is empty or index out of bounds
                     btn.configure(fg_color=original_fg_color, text_color=TEXT)


    # ── NEW: Unified UI Playback State Updater ────────────────

    def _update_playback_ui_state(self):
        """
        Updates the UI elements (active song label, highlight, status, Discord RPC)
        based on the current state of the VLCMusicEngine.
        This should be called whenever the engine's playback state or index might have changed.
        """
        current_engine_index = self.engine.index
        is_playing = self.engine.is_playing()
        engine_state = self.engine.get_state()

        # Update active song highlight if index has changed
        if current_engine_index != self.active_index:
            self.active_index = current_engine_index
            self._highlight_active()
            # If the index changed, it implies a new song is starting or has changed state
            self.update_discord_song(force_update=True) # Force update Discord RPC

        # Update current song label
        if self.engine.playlist and 0 <= self.active_index < len(self.engine.playlist):
            self.current_song_label.configure(
                text=os.path.basename(self.engine.playlist[self.active_index]))
        else:
            self.current_song_label.configure(text="Nothing playing")


        # Update status label
        if is_playing:
            self.status.configure(text=f"Playing ▶ Track {self.active_index + 1}")
            # If we are playing, ensure Discord RPC is updated
            if not self._discord_rpc_active:
                self.update_discord_song(force_update=True)
        elif engine_state == State.Paused:
            self.status.configure(text="Paused ⏸")
            # Clear Discord RPC if transitioning to paused from playing
            if self._discord_rpc_active:
                self.update_discord_song(force_clear=True)
        elif (current_engine_index == -1 and not self.engine.playlist) or \
             (current_engine_index == -1 and self.engine.playlist and engine_state == State.Stopped):
            # No songs loaded OR Playlist loaded but stopped (e.g., after stop button or end of playlist without repeat)
            self.status.configure(text="Idle" if not self.engine.playlist else "Stopped")
            # Clear Discord RPC if not playing and RPC was active
            if self._discord_rpc_active:
                self.update_discord_song(force_clear=True)
        elif engine_state == State.Ended: # Should usually be caught by next song playing, but as fallback
            self.status.configure(text="Finished")
            # Clear Discord RPC if truly finished and RPC was active
            if self._discord_rpc_active:
                self.update_discord_song(force_clear=True)

    # ──────────────────────────────────────────────────────────

    # ── Helpers ───────────────────────────────────────────

    def get_song_info(self, filepath):
        try:
            audio = MutagenFile(filepath, easy=True)
            if audio:
                title = None
                artist = None

                if "title" in audio:
                    title = audio["title"][0]

                if "artist" in audio:
                    artist = audio["artist"][0]

                if artist and title:
                    return f"{artist} - {title}"
                if title:
                    return title
        except Exception:
            pass
        return os.path.basename(filepath)

    def update_discord_song(self, force_clear=False, force_update=False): # Added flags
        try:
            discord_service = self.manager.container.discord_service

            if force_clear:
                if self._discord_rpc_active: # Only clear if it was active
                    discord_service.clear()
                    self._discord_rpc_active = False
                return

            if self.engine.index < 0 or not self.engine.is_playing():
                if self._discord_rpc_active: # Only clear if it was active
                    discord_service.clear()
                    self._discord_rpc_active = False
                return

            filepath = self.engine.playlist[self.engine.index]
            song = self.get_song_info(filepath)

            # Only update RPC if a change is needed or forced
            if force_update or not self._discord_rpc_active or \
               (self._discord_rpc_active and discord_service.last_details != "🎵 Listening to Music") or \
               (self._discord_rpc_active and discord_service.last_state != song): # Assuming last_details/state exists in DiscordService
                discord_service.update(
                    "🎵 Listening to Music",
                    song
                )
                self._discord_rpc_active = True # Mark RPC as active
                # To prevent unnecessary updates, you might also want to store
                # the last updated details/state in DiscordService and check against them.

        except Exception as e:
            print(f"Error updating Discord RPC: {e}")
            # Ensure Discord status is cleared on error and mark RPC as inactive
            if self._discord_rpc_active:
                try:
                    discord_service.clear()
                except Exception:
                    pass
                self._discord_rpc_active = False