# modules/music_player/mini_widget.py
#
# Compact "now playing" readout for the catalog card. Shares manager.music_engine
# and manager.music_db with the full Music Player page.

from __future__ import annotations

import os
import threading

import customtkinter as ctk

from core import theme
from core.module_themes import get_saved_module_theme, resolve_module_theme
from ._buttons import seek_bar_kwargs

MODULE_ID = "Media Player"
REFRESH_MS = 1000
REFRESH_PLAYING_MS = 350


def _fmt_track(meta, fallback_path: str | None) -> str:
    if meta:
        title = meta.get("title") or os.path.basename(meta.get("path") or fallback_path or "?")
        artist = meta.get("artist")
        return f"{artist} - {title}" if artist else title
    return os.path.basename(fallback_path or "?")


class MusicMiniWidget(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color="transparent")
        self.manager = manager
        self._music_theme = self._resolve_music_theme()

        self.grid_columnconfigure(0, weight=1)

        self.track_label = ctk.CTkLabel(
            self,
            text="Nothing playing",
            font=theme.font(11),
            text_color=theme.MUTED,
            anchor="w",
        )
        self.track_label.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        self._seek_dragging = False
        self._seek_programmatic = False
        self._seek_track_length = 0.0
        self._engine_init_started = False
        self._library_load_started = False
        self._pending_action = None

        self.seek_slider = ctk.CTkSlider(
            self,
            from_=0,
            to=1,
            number_of_steps=500,
            height=12,
            command=self._on_seek_slide,
            **seek_bar_kwargs(t=self._music_theme),
        )
        self.seek_slider.set(0)
        self.seek_slider.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self.seek_slider.bind("<ButtonRelease-1>", self._on_seek_release)
        self.seek_slider.bind("<Button-1>", self._on_seek_press)

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.grid(row=2, column=0, sticky="w")

        btn_kw = dict(
            width=30,
            height=26,
            fg_color=theme.PANEL_2,
            hover_color=theme.PANEL_HOVER,
            text_color=theme.TEXT,
            corner_radius=6,
            font=theme.font(12),
        )

        self.prev_btn = ctk.CTkButton(controls, text="⏮", command=self._prev, **btn_kw)
        self.prev_btn.pack(side="left", padx=(0, 4))

        self.play_btn = ctk.CTkButton(controls, text="▶", command=self._toggle_play, **btn_kw)
        self.play_btn.pack(side="left", padx=(0, 4))

        self.next_btn = ctk.CTkButton(controls, text="⏭", command=self._next, **btn_kw)
        self.next_btn.pack(side="left")

        self._set_controls_enabled(False)
        self._set_seek_enabled(False)
        self._kickoff_runtime()
        self._tick()

    # ── theme / runtime ──────────────────────────────────────

    def _resolve_music_theme(self):
        try:
            container = getattr(self.manager, "container", None)
            settings = getattr(container, "settings", None) if container else None
            if settings is None:
                settings = getattr(self.manager, "settings", None)
            if settings is None:
                return theme
            tid = get_saved_module_theme(settings, MODULE_ID)
            return resolve_module_theme(tid).t
        except Exception:
            return theme

    def _kickoff_runtime(self):
        """Warm up DB + VLC in the background so the catalog controls work."""
        self._db()
        self._start_engine_init()

    def _db(self):
        db = getattr(self.manager, "music_db", None)
        if db is None:
            from . import db as musicdb
            db = musicdb.Library()
            self.manager.music_db = db
        return db

    def _engine(self):
        return getattr(self.manager, "music_engine", None)

    def _start_engine_init(self):
        if self._engine() is not None or self._engine_init_started:
            return
        self._engine_init_started = True

        def worker():
            try:
                from .player import VLCMusicEngine
                eng = VLCMusicEngine()
            except Exception as exc:
                print(f"[MusicMiniWidget] VLC init failed: {exc}")
                eng = None

            def apply():
                self._engine_init_started = False
                if not self.winfo_exists():
                    return
                if eng is not None:
                    self.manager.music_engine = eng
                    web = getattr(self.manager, "music_web_server", None)
                    if web is not None:
                        web.engine = eng
                if self._pending_action:
                    action = self._pending_action
                    self._pending_action = None
                    self._ensure_queue_then(action)
                self._tick()

            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def _ensure_queue_then(self, callback):
        engine = self._engine()
        if engine is None:
            self._pending_action = callback
            self.track_label.configure(text="Starting audio…", text_color=theme.MUTED)
            self._start_engine_init()
            return

        if engine.playlist:
            callback()
            return

        if self._library_load_started:
            self._pending_action = callback
            return

        self._library_load_started = True
        self.track_label.configure(text="Loading library…", text_color=theme.MUTED)

        def worker():
            db = self._db()
            ids = getattr(self.manager, "music_library_ids", None)
            if ids is None:
                try:
                    ids = db.all_ids()
                    self.manager.music_library_ids = ids
                except Exception as exc:
                    print(f"[MusicMiniWidget] library load failed: {exc}")
                    ids = None

            def apply():
                self._library_load_started = False
                if not self.winfo_exists():
                    return
                if engine is not None and ids is not None and len(ids):
                    engine.load_ids(db, ids, start_index=0)
                pending = self._pending_action
                self._pending_action = None
                if len(ids or []) == 0:
                    self.track_label.configure(
                        text="Library empty — open Music Player",
                        text_color=theme.MUTED,
                    )
                    return
                callback()
                if pending and pending is not callback:
                    pending()

            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    # ── controls ─────────────────────────────────────────────

    def _set_controls_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        for btn in (self.prev_btn, self.play_btn, self.next_btn):
            btn.configure(state=state)

    def _set_seek_enabled(self, enabled):
        try:
            self.seek_slider.configure(state="normal" if enabled else "disabled")
        except Exception:
            pass

    def _toggle_play(self):
        def action():
            engine = self._engine()
            if not engine:
                return
            if engine.is_playing():
                engine.pause()
            else:
                engine.play()

        self._ensure_queue_then(action)

    def _on_seek_press(self, _event=None):
        self._seek_dragging = True

    def _on_seek_slide(self, _value):
        if self._seek_programmatic:
            return
        self._seek_dragging = True

    def _on_seek_release(self, _event=None):
        engine = self._engine()
        if not engine:
            self._seek_dragging = False
            return
        total = max(0.0, engine.get_length())
        if total > 0:
            engine.seek(float(self.seek_slider.get()) * total)
        self._seek_dragging = False

    def _next(self):
        def action():
            eng = self._engine()
            if eng:
                eng.next()

        self._ensure_queue_then(action)

    def _prev(self):
        def action():
            eng = self._engine()
            if eng:
                eng.prev()

        self._ensure_queue_then(action)

    def _has_track(self, engine) -> bool:
        return (
            engine is not None
            and engine.playlist
            and 0 <= engine.index < len(engine.playlist)
        )

    # ── refresh loop ─────────────────────────────────────────

    def _tick(self):
        if not self.winfo_exists():
            return

        delay = REFRESH_MS
        try:
            engine = self._engine()

            if not self._has_track(engine):
                self.track_label.configure(text="Nothing playing", text_color=theme.MUTED)
                self._seek_programmatic = True
                self.seek_slider.set(0)
                self._seek_programmatic = False
                self._set_controls_enabled(engine is not None)
                self._set_seek_enabled(False)
                self.play_btn.configure(text="▶")
            else:
                self._set_controls_enabled(True)
                self._set_seek_enabled(True)

                meta = engine.get_current_meta()
                path = engine.playlist[engine.index]
                name = _fmt_track(meta, path)
                if len(name) > 34:
                    name = name[:31] + "..."
                self.track_label.configure(text=name, text_color=self._music_theme.ACCENT)

                is_playing = engine.is_playing()
                self.play_btn.configure(text="⏸" if is_playing else "▶")
                if is_playing:
                    delay = REFRESH_PLAYING_MS

                length = engine.get_length()
                pos = engine.get_time()
                self._seek_track_length = max(0.0, length)
                if not self._seek_dragging and length:
                    self._seek_programmatic = True
                    self.seek_slider.set(pos / length)
                    self._seek_programmatic = False
        except Exception:
            pass

        self.after(delay, self._tick)


def build(parent, manager):
    return MusicMiniWidget(parent, manager)
