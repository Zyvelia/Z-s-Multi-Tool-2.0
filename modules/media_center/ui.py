import os
import sys

import customtkinter as ctk
from tkinter import filedialog
import vlc

from .player import VLCMediaEngine
from core import theme

# ── Colours (matches the app's shared dark theme) ─────────────────────────
BG = theme.BG
PANEL = theme.PANEL
PANEL_2 = theme.PANEL_2
ACCENT = theme.ACCENT
TEXT = theme.TEXT
MUTED = theme.MUTED

_BTN = dict(fg_color=PANEL_2, hover_color=theme.PANEL_HOVER, text_color=TEXT, height=34, corner_radius=8)
_BTN_ACCENT = dict(fg_color=ACCENT, hover_color=theme.ACCENT_DIM, text_color="white", height=34, corner_radius=8)
_ICON_BTN = dict(
    fg_color=PANEL_2, hover_color="#232a3a", text_color=TEXT,
    width=46, height=40, corner_radius=10, font=("Segoe UI", 15),
)
_ICON_BTN_ACCENT = {**_ICON_BTN, "fg_color": ACCENT, "hover_color": "#2f7fd6", "text_color": "white"}


def _make_btn(parent, text, cmd, **overrides):
    return ctk.CTkButton(parent, text=text, command=cmd, **{**_BTN, **overrides})


class MediaCenterPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=BG)
        self.manager = manager

        if hasattr(manager, "media_engine"):
            self.engine = manager.media_engine
        else:
            self.engine = VLCMediaEngine()
            manager.media_engine = self.engine

        self.song_buttons = []
        self.song_names = []
        self.active_index = -1

        self.is_fullscreen = False
        self._fs_root = None

        self.build_ui()
        self.after(300, self.update_loop)

    # =====================================================
    # BUILD
    # =====================================================

    def build_ui(self):
        self._build_header()
        self._build_video_panel()
        self._build_playlist()
        self._build_progress()
        self._build_controls()
        self._build_load_button()
        self._build_volume()

    def _build_header(self):
        self.header = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        self.header.pack(fill="x", padx=15, pady=(15, 8))

        ctk.CTkLabel(
            self.header, text="🎬  Media Center", font=("Segoe UI", 22, "bold"), text_color=TEXT,
        ).pack(side="left", padx=10)

        self.status = ctk.CTkLabel(self.header, text="Ready", text_color=MUTED)
        self.status.pack(side="right", padx=15)

    def _build_video_panel(self):
        self.video_frame = ctk.CTkFrame(self, fg_color="black", corner_radius=10, height=320)
        self.video_frame.pack(fill="x", padx=15, pady=(0, 8))
        self.video_frame.pack_propagate(False)

        self.video_label = ctk.CTkLabel(
            self.video_frame, text="No Video Loaded", text_color=MUTED, font=("Segoe UI", 14),
        )
        self.video_label.pack(expand=True)

        # Double-click the video area to toggle fullscreen, like most players.
        self.video_frame.bind("<Double-Button-1>", lambda _e: self.toggle_fullscreen())

    def _build_playlist(self):
        self.playlist_frame = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        self.playlist_frame.pack(fill="both", expand=True, padx=15, pady=8)

        ctk.CTkLabel(
            self.playlist_frame, text="Playlist", font=("Segoe UI", 15, "bold"), text_color=TEXT,
        ).pack(anchor="w", padx=12, pady=(10, 4))

        self.song_frame = ctk.CTkScrollableFrame(self.playlist_frame, fg_color=PANEL_2, corner_radius=8)
        self.song_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _build_progress(self):
        self.progress_row = ctk.CTkFrame(self, fg_color="transparent")
        self.progress_row.pack(fill="x", padx=15, pady=(0, 4))

        self.progress = ctk.CTkProgressBar(self.progress_row, progress_color=ACCENT)
        self.progress.set(0)
        self.progress.pack(fill="x")

        self.time_label = ctk.CTkLabel(self, text="00:00 / 00:00", text_color=MUTED, font=("Segoe UI", 11))
        self.time_label.pack(pady=(2, 8))

    def _build_controls(self):
        self.controls = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        self.controls.pack(pady=(0, 8))

        inner = ctk.CTkFrame(self.controls, fg_color="transparent")
        inner.pack(padx=10, pady=10)

        ctk.CTkButton(inner, text="⏮", command=self.prev, **_ICON_BTN).grid(row=0, column=0, padx=4)
        ctk.CTkButton(inner, text="▶", command=self.play, **_ICON_BTN_ACCENT).grid(row=0, column=1, padx=4)
        ctk.CTkButton(inner, text="⏸", command=self.pause, **_ICON_BTN).grid(row=0, column=2, padx=4)
        ctk.CTkButton(inner, text="⏭", command=self.next, **_ICON_BTN).grid(row=0, column=3, padx=4)

        self.fullscreen_btn = ctk.CTkButton(
            inner, text="⛶ Fullscreen", command=self.toggle_fullscreen, **{**_BTN, "width": 140},
        )
        self.fullscreen_btn.grid(row=0, column=4, padx=(16, 4))

    def _build_load_button(self):
        self.load_btn = ctk.CTkButton(
            self, text="📂  Open Media Files", command=self.load_files,
            font=("Segoe UI", 13, "bold"), **_BTN_ACCENT,
        )
        self.load_btn.pack(pady=(0, 8))

    def _build_volume(self):
        self.volume_frame = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        self.volume_frame.pack(fill="x", padx=15, pady=(0, 15))

        inner = ctk.CTkFrame(self.volume_frame, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=10)

        ctk.CTkLabel(inner, text="🔈", text_color=MUTED, font=("Segoe UI", 14)).pack(side="left", padx=(0, 10))

        self.volume = ctk.CTkSlider(
            inner, from_=0, to=1, progress_color=ACCENT,
            button_color=ACCENT, button_hover_color="#2f7fd6", command=self.set_volume,
        )
        self.volume.set(0.5)
        self.volume.pack(side="left", fill="x", expand=True)

        self.volume_pct = ctk.CTkLabel(inner, text="50%", text_color=MUTED, width=40)
        self.volume_pct.pack(side="left", padx=(10, 0))

    # =====================================================
    # FILES
    # =====================================================

    def load_files(self):
        files = filedialog.askopenfilenames(
            filetypes=[
                ("Media Files", "*.mp3 *.wav *.flac *.ogg *.m4a *.mp4 *.mkv *.avi *.mov *.webm")
            ]
        )
        if not files:
            return

        self.engine.load(files)

        for b in self.song_buttons:
            b.destroy()
        self.song_buttons.clear()
        self.song_names = [os.path.basename(f) for f in files]

        for i, name in enumerate(self.song_names):
            btn = ctk.CTkButton(
                self.song_frame,
                text=self._track_label(i, name, active=False),
                anchor="w",
                fg_color=PANEL,
                hover_color="#232a3a",
                text_color=TEXT,
                corner_radius=6,
                height=32,
                command=lambda idx=i: self.play_song(idx),
            )
            btn.pack(fill="x", padx=2, pady=2)
            self.song_buttons.append(btn)

        self.status.configure(text=f"{len(files)} file(s) loaded")

    @staticmethod
    def _track_label(index, name, active):
        marker = "▶" if active else " "
        return f" {marker}  {index + 1:02d}   {name}"

    # =====================================================
    # PLAYBACK
    # =====================================================

    def play_song(self, index):
        self.active_index = index
        self.setup_video_output()
        self.engine.play_at(index)
        self.update_highlight()

    def play(self):
        self.setup_video_output()
        self.engine.play()
        self.active_index = self.engine.index
        self.update_highlight()

    def pause(self):
        self.engine.pause()

    def next(self):
        self.engine.next()
        self.active_index = self.engine.index
        self.update_highlight()

    def prev(self):
        self.engine.prev()
        self.active_index = self.engine.index
        self.update_highlight()

    def set_volume(self, value):
        self.engine.set_volume(value)
        try:
            self.volume_pct.configure(text=f"{int(float(value) * 100)}%")
        except (TypeError, ValueError):
            pass

    # =====================================================
    # UI
    # =====================================================

    def update_highlight(self):
        for i, button in enumerate(self.song_buttons):
            active = i == self.active_index
            button.configure(
                text=self._track_label(i, self.song_names[i], active),
                fg_color=ACCENT if active else PANEL,
                text_color="white" if active else TEXT,
            )

    def setup_video_output(self):
        self.update()  # Ensure the frame has a real window id before we grab it.
        handle = self.video_frame.winfo_id()

        try:
            if sys.platform.startswith("win"):
                self.engine.player.set_hwnd(handle)
            elif sys.platform == "linux":
                self.engine.player.set_xwindow(handle)
            elif sys.platform == "darwin":
                self.engine.player.set_nsobject(handle)
        except Exception as e:
            print("Video output error:", e)

    # =====================================================
    # FULLSCREEN
    # =====================================================
    # libvlc's own toggle_fullscreen() has no effect here because the video
    # is embedded inside a Tkinter frame (via set_hwnd/set_xwindow) rather
    # than owning its own top-level window. Instead we make the app window
    # itself go fullscreen and let the (already-embedded) video frame
    # expand to fill it — the same approach real embedded players use.

    def toggle_fullscreen(self):
        if self.is_fullscreen:
            self.exit_fullscreen()
        else:
            self.enter_fullscreen()

    def enter_fullscreen(self):
        if self.is_fullscreen:
            return
        self.is_fullscreen = True

        root = self.winfo_toplevel()
        self._fs_root = root

        # Hide everything except the video panel so it can take over the window.
        self.header.pack_forget()
        self.playlist_frame.pack_forget()
        self.progress_row.pack_forget()
        self.time_label.pack_forget()
        self.controls.pack_forget()
        self.load_btn.pack_forget()
        self.volume_frame.pack_forget()

        self.video_frame.pack_forget()
        self.video_frame.pack(fill="both", expand=True, padx=0, pady=0)

        try:
            root.attributes("-fullscreen", True)
        except Exception:
            pass

        root.bind("<Escape>", self._on_escape)
        self.fullscreen_btn.configure(text="⛶ Exit Fullscreen")

    def _on_escape(self, _event=None):
        self.exit_fullscreen()

    def exit_fullscreen(self):
        if not self.is_fullscreen:
            return
        self.is_fullscreen = False

        root = self._fs_root
        if root is not None:
            try:
                root.attributes("-fullscreen", False)
            except Exception:
                pass
            try:
                root.unbind("<Escape>")
            except Exception:
                pass

        self.video_frame.pack_forget()

        # Re-pack everything in its original top-to-bottom order.
        self.header.pack(fill="x", padx=15, pady=(15, 8))
        self.video_frame.pack(fill="x", padx=15, pady=(0, 8))
        self.playlist_frame.pack(fill="both", expand=True, padx=15, pady=8)
        self.progress_row.pack(fill="x", padx=15, pady=(0, 4))
        self.time_label.pack(pady=(2, 8))
        self.controls.pack(pady=(0, 8))
        self.load_btn.pack(pady=(0, 8))
        self.volume_frame.pack(fill="x", padx=15, pady=(0, 15))

        self.fullscreen_btn.configure(text="⛶ Fullscreen")

    # =====================================================
    # LOOP
    # =====================================================

    def update_loop(self):
        current = self.engine.get_time()
        total = self.engine.get_length()

        if total > 0:
            self.progress.set(current / total)
            self.time_label.configure(
                text=f"{int(current // 60):02}:{int(current % 60):02} / "
                     f"{int(total // 60):02}:{int(total % 60):02}"
            )

        state = self.engine.get_state()

        if state in (vlc.State.Ended, vlc.State.Stopped):
            if self.engine.index + 1 < len(self.engine.playlist):
                self.next()

        self.after(300, self.update_loop)