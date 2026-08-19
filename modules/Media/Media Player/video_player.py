# Video Player tab (formerly the standalone `media_center` package).
#
# Folded in here as a single file since it's only ever used from
# music_player/ui.py as an extra tab — no need for it to be its own
# top-level modules/media_center package anymore. It keeps its own
# separate VLCMediaEngine (manager.media_engine), so there's no
# conflict with MusicPage's own music engine.
import os
import random
import sys
import time

import customtkinter as ctk
from tkinter import filedialog
import vlc

from core import theme
from .media_types import file_dialog_video_types
from ._buttons import (
    cool_button_kwargs, make_btn as _make_btn, icon_btn_kwargs as _icon_btn_kwargs,
    cool_accent, cool_accent_hover, selected_track_kwargs, highlight_fill_hover,
    highlight_border, play_button_kwargs,
)


def _icon_btn_accent_kwargs(**overrides):
    return play_button_kwargs(width=52, **overrides)


# =====================================================
# ENGINE
# =====================================================

class VLCMediaEngine:

    def __init__(self):
        self.instance = vlc.Instance()
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


# =====================================================
# UI
# =====================================================

class VideoPlayerPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=theme.BG)
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

        self.is_popped_out = False
        self.popout_window = None
        self.popout_video_frame = None

        self.build_ui()
        self.after(300, self.update_loop)

    # =====================================================
    # BUILD
    # =====================================================
    #
    # Pack order matters here. Everything below the video panel used to
    # be packed top-down after the (expand=True) playlist, which meant
    # the transport controls / load button / volume bar only got
    # whatever cavity was left over — on a short window they'd get
    # pushed past the bottom edge and become invisible until you
    # manually resized the window taller.
    #
    # Fix: anchor the video panel to the top and the controls/load/volume
    # row to the bottom (side="bottom"), and build the bottom group in
    # reverse visual order so the first one packed claims the very
    # bottom edge. Only the playlist (packed last, fill="both",
    # expand=True) is left to grow/shrink with whatever space remains
    # in between — so it's the one that scrolls/shrinks, never the
    # controls.

    def build_ui(self):
        self._build_header()
        self._build_video_panel()

        # Bottom-anchored, built bottom-most-first so the visual order
        # top-to-bottom stays: progress bar, time, controls, load
        # button, volume — with volume sitting flush against the
        # window's bottom edge no matter how short the window gets.
        self._build_volume()
        self._build_load_button()
        self._build_controls()
        self._build_progress()

        # Flexible middle - takes whatever space is left, shrinks first.
        self._build_playlist()

    def _build_header(self):
        self.header = ctk.CTkFrame(
            self, fg_color=theme.PANEL, corner_radius=10,
            border_width=1, border_color=theme.BORDER,
        )
        self.header.pack(side="top", fill="x", padx=15, pady=(15, 8))

        ctk.CTkLabel(
            self.header, text="🎬  Video Player",
            font=("Segoe UI", 22, "bold"), text_color=theme.TEXT,
        ).pack(side="left", padx=10)

        self.status = ctk.CTkLabel(
            self.header, text="Ready", text_color=theme.TEXT,
            font=("Segoe UI", 12, "bold"),
        )
        self.status.pack(side="right", padx=15)

    def _build_video_panel(self):
        self.video_frame = ctk.CTkFrame(
            self, fg_color="black", corner_radius=10, height=320,
            border_width=2, border_color=theme.BORDER,
        )
        self.video_frame.pack(side="top", fill="x", padx=15, pady=(0, 8))
        self.video_frame.pack_propagate(False)

        self.video_label = ctk.CTkLabel(
            self.video_frame, text="No Video Loaded",
            text_color=theme.MUTED, font=("Segoe UI", 15),
        )
        self.video_label.pack(expand=True)

        # Double-click the video area to toggle fullscreen, like most players.
        self.video_frame.bind("<Double-Button-1>", lambda _e: self.toggle_fullscreen())

        # Shown in the video_frame's spot instead of the video itself while
        # popped out (see toggle_popout below) - keeps the layout from
        # jumping around and makes it obvious where the video went.
        self.popout_placeholder = ctk.CTkFrame(
            self, fg_color=theme.PANEL_2, corner_radius=10, height=60,
            border_width=1, border_color=theme.ACCENT_DIM,
        )
        self.popout_placeholder.pack_propagate(False)
        ctk.CTkLabel(
            self.popout_placeholder, text="🗗  Video is playing in its own window",
            text_color=theme.TEXT, font=("Segoe UI", 13, "bold"),
        ).pack(expand=True)

    def _build_playlist(self):
        self.playlist_frame = ctk.CTkFrame(
            self, fg_color=theme.PANEL, corner_radius=10,
            border_width=1, border_color=theme.BORDER,
        )
        self.playlist_frame.pack(side="top", fill="both", expand=True, padx=15, pady=8)

        top = ctk.CTkFrame(self.playlist_frame, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(10, 4))

        ctk.CTkLabel(
            top, text="Playlist", font=("Segoe UI", 16, "bold"), text_color=theme.TEXT,
        ).pack(side="left")

        self.playlist_count = ctk.CTkLabel(
            top, text="0 files", text_color=theme.TEXT, font=("Segoe UI", 12, "bold"),
        )
        self.playlist_count.pack(side="right")

        self.song_frame = ctk.CTkScrollableFrame(
            self.playlist_frame, fg_color=theme.BG, corner_radius=8,
            border_width=1, border_color=theme.BORDER,
            scrollbar_button_color=theme.PANEL_2,
            scrollbar_button_hover_color=theme.PANEL_HOVER,
        )
        self.song_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _build_progress(self):
        self.progress_card = ctk.CTkFrame(
            self, fg_color=theme.PANEL_2, corner_radius=10,
            border_width=1, border_color=theme.BORDER,
        )
        self.progress_card.pack(side="bottom", fill="x", padx=15, pady=(0, 6))

        self.time_label = ctk.CTkLabel(
            self.progress_card, text="00:00 / 00:00",
            text_color=theme.TEXT, font=("Consolas", 12),
        )
        self.time_label.pack(anchor="w", padx=12, pady=(8, 2))

        self.progress = ctk.CTkProgressBar(
            self.progress_card, progress_color=cool_accent(),
            fg_color=theme.BORDER, corner_radius=4, height=10,
        )
        self.progress.set(0)
        self.progress.pack(fill="x", padx=12, pady=(0, 10))

    def _build_controls(self):
        self.controls = ctk.CTkFrame(
            self, fg_color=theme.PANEL, corner_radius=10,
            border_width=1, border_color=theme.BORDER,
        )
        self.controls.pack(side="bottom", pady=(0, 8))

        inner = ctk.CTkFrame(self.controls, fg_color="transparent")
        inner.pack(padx=10, pady=10)

        ctk.CTkButton(inner, text="⏮", command=self.prev, **_icon_btn_kwargs()).grid(row=0, column=0, padx=4)
        ctk.CTkButton(inner, text="▶", command=self.play, **_icon_btn_accent_kwargs()).grid(row=0, column=1, padx=4)
        ctk.CTkButton(inner, text="⏸", command=self.pause, **_icon_btn_kwargs()).grid(row=0, column=2, padx=4)
        ctk.CTkButton(inner, text="⏭", command=self.next, **_icon_btn_kwargs()).grid(row=0, column=3, padx=4)

        fs_kw = cool_button_kwargs(width=140)
        self.fullscreen_btn = ctk.CTkButton(
            inner, text="⛶ Fullscreen", command=self.toggle_fullscreen, **fs_kw,
        )
        self.fullscreen_btn.grid(row=0, column=4, padx=(16, 4))

        pop_kw = cool_button_kwargs(width=130)
        self.popout_btn = ctk.CTkButton(
            inner, text="🗗 Pop Out", command=self.toggle_popout, **pop_kw,
        )
        self.popout_btn.grid(row=0, column=5, padx=4)

    def _build_load_button(self):
        load_kw = theme.primary_button_kwargs()
        load_kw["font"] = ("Segoe UI", 13, "bold")
        self.load_btn = ctk.CTkButton(
            self, text="📂  Open Media Files", command=self.load_files,
            **load_kw,
        )
        self.load_btn.pack(side="bottom", fill="x", padx=15, pady=(0, 8))

    def _build_volume(self):
        self.volume_frame = ctk.CTkFrame(
            self, fg_color=theme.PANEL, corner_radius=10,
            border_width=1, border_color=theme.BORDER,
        )
        self.volume_frame.pack(side="bottom", fill="x", padx=15, pady=(0, 15))

        inner = ctk.CTkFrame(self.volume_frame, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=10)

        ctk.CTkLabel(
            inner, text="Volume", text_color=theme.TEXT,
            font=("Segoe UI", 12, "bold"),
        ).pack(side="left", padx=(0, 10))

        self.volume = ctk.CTkSlider(
            inner, from_=0, to=1, progress_color=cool_accent(),
            button_color=cool_accent(), button_hover_color=cool_accent_hover(),
            fg_color=theme.BORDER, command=self.set_volume, corner_radius=4, height=16,
        )
        self.volume.set(0.5)
        self.volume.pack(side="left", fill="x", expand=True)

        self.volume_pct = ctk.CTkLabel(
            inner, text="50%", text_color=theme.TEXT, width=44,
            font=("Segoe UI", 12, "bold"),
        )
        self.volume_pct.pack(side="left", padx=(10, 0))

    # =====================================================
    # FILES
    # =====================================================

    def load_files(self):
        files = filedialog.askopenfilenames(filetypes=file_dialog_video_types())
        if not files:
            return

        self.engine.load(files)

        for b in self.song_buttons:
            b.destroy()
        self.song_buttons.clear()
        self.song_names = [os.path.basename(f) for f in files]

        for i, name in enumerate(self.song_names):
            row = ctk.CTkFrame(
                self.song_frame, fg_color=theme.PANEL_2, corner_radius=6,
                border_width=1, border_color=theme.BORDER,
            )
            row.pack(fill="x", padx=4, pady=2)

            btn = ctk.CTkButton(
                row,
                text=self._track_label(i, name, active=False),
                anchor="w",
                fg_color="transparent",
                hover_color=highlight_fill_hover(),
                text_color=theme.TEXT,
                font=("Segoe UI", 13),
                corner_radius=6,
                height=34,
                command=lambda idx=i: self.play_song(idx),
            )
            btn.pack(side="left", fill="x", expand=True, padx=2, pady=1)
            self.song_buttons.append(btn)

        count = len(files)
        self.playlist_count.configure(text=f"{count} file{'s' if count != 1 else ''}")
        self.status.configure(text=f"{count} file(s) loaded", text_color=theme.TEXT)

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
                **(selected_track_kwargs() if active else dict(
                    fg_color="transparent",
                    hover_color=highlight_fill_hover(),
                    text_color=theme.TEXT,
                    font=("Segoe UI", 13),
                )),
            )
            button.master.configure(border_color=highlight_border() if active else theme.BORDER)

    def setup_video_output(self):
        # Renders into the popout window's frame instead of the embedded
        # one if the video's currently popped out.
        target = self.popout_video_frame if self.is_popped_out else self.video_frame

        target.update()  # Ensure the frame has a real window id before we grab it.
        handle = target.winfo_id()

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
        if self.is_popped_out:
            # Fullscreening this window doesn't make sense while the video
            # is actually rendering into the separate popout window instead
            # - maximize that window (normal OS title bar controls) to get
            # the same effect.
            return
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
        self.progress_card.pack_forget()
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

        # Re-pack everything, same sides/order as build_ui so the
        # "controls always visible" fix still holds after returning
        # from fullscreen.
        self.header.pack(side="top", fill="x", padx=15, pady=(15, 8))
        self.video_frame.pack(side="top", fill="x", padx=15, pady=(0, 8))

        self.volume_frame.pack(side="bottom", fill="x", padx=15, pady=(0, 15))
        self.load_btn.pack(side="bottom", fill="x", padx=15, pady=(0, 8))
        self.controls.pack(side="bottom", pady=(0, 8))
        self.progress_card.pack(side="bottom", fill="x", padx=15, pady=(0, 6))

        self.playlist_frame.pack(side="top", fill="both", expand=True, padx=15, pady=8)

        self.fullscreen_btn.configure(text="⛶ Fullscreen")

    # =====================================================
    # POP OUT (video in its own floating window)
    # =====================================================
    # VLC renders by being handed a raw window handle (set_hwnd/set_xwindow/
    # set_nsobject), not through Tkinter's normal parent-child widget tree -
    # so "popping out" doesn't require reparenting a widget (Tkinter has no
    # real way to do that across top-level windows anyway). We just build a
    # frame in a separate CTkToplevel and redirect VLC's output handle to
    # it instead, same mechanism as embedding, just pointed somewhere else.

    def toggle_popout(self):
        if self.is_popped_out:
            self.dock_video_back()
        else:
            self.pop_out_video()

    def pop_out_video(self):
        if self.is_popped_out:
            return

        if self.is_fullscreen:
            self.exit_fullscreen()

        self.popout_window = ctk.CTkToplevel(self)
        self.popout_window.title("Media Center - Video")
        self.popout_window.geometry("960x540")
        self.popout_window.configure(fg_color="black")
        # Closing the popout window (X button) docks the video back into
        # the tab rather than just vanishing - VLC would otherwise be left
        # rendering to a handle that no longer exists.
        self.popout_window.protocol("WM_DELETE_WINDOW", self.dock_video_back)

        self.popout_video_frame = ctk.CTkFrame(self.popout_window, fg_color="black", corner_radius=0)
        self.popout_video_frame.pack(fill="both", expand=True)
        self.popout_video_frame.bind("<Double-Button-1>", lambda _e: self._maximize_popout())

        # Swap the embedded slot for the "video is elsewhere" placeholder.
        self.video_frame.pack_forget()
        self.popout_placeholder.pack(side="top", fill="x", padx=15, pady=(0, 8), before=self.playlist_frame)

        self.is_popped_out = True
        self.popout_btn.configure(text="🗗 Dock Back")
        self.fullscreen_btn.configure(state="disabled")

        # Re-point VLC's output at the new window instead of the (now
        # hidden) embedded frame.
        self.setup_video_output()

    def dock_video_back(self):
        if not self.is_popped_out:
            return

        self.popout_placeholder.pack_forget()
        self.video_frame.pack(side="top", fill="x", padx=15, pady=(0, 8), before=self.playlist_frame)

        if self.popout_window is not None:
            try:
                self.popout_window.protocol("WM_DELETE_WINDOW", lambda: None)
                self.popout_window.destroy()
            except Exception:
                pass
        self.popout_window = None
        self.popout_video_frame = None

        self.is_popped_out = False
        self.popout_btn.configure(text="🗗 Pop Out")
        self.fullscreen_btn.configure(state="normal")

        # Re-point VLC's output back at the embedded frame.
        self.setup_video_output()

    def _maximize_popout(self):
        if self.popout_window is None:
            return
        try:
            is_zoomed = self.popout_window.state() == "zoomed"
            self.popout_window.state("normal" if is_zoomed else "zoomed")
        except Exception:
            pass

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

        if self.engine.is_playing():
            name = ""
            if 0 <= self.active_index < len(self.song_names):
                name = self.song_names[self.active_index]
            self.status.configure(
                text=f"Playing ▶  {name}" if name else "Playing ▶",
                text_color=theme.ACCENT,
            )
            self.video_label.configure(text="")
        elif state == vlc.State.Paused:
            self.status.configure(text="Paused ⏸", text_color=theme.MUTED)
        elif self.engine.playlist:
            self.status.configure(text="Stopped", text_color=theme.TEXT)
        else:
            self.status.configure(text="Ready", text_color=theme.TEXT)

        if state in (vlc.State.Ended, vlc.State.Stopped):
            if self.engine.index + 1 < len(self.engine.playlist):
                self.next()

        self.after(300, self.update_loop)