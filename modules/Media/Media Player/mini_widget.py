# modules/music_player/mini_widget.py
#
# Compact "now playing" readout for the catalog card. Doesn't create its
# own player — it reads the SAME shared engine the full Music Player page
# uses (manager.music_engine), so controls here and in the full page stay
# in sync automatically.
#
# Important: that engine only exists once the Music Player has been opened
# at least once this session (see ui.py's MusicPage.__init__). Until then
# there's nothing to show, so the widget displays an idle state and just
# keeps checking — no engine needs to be created just to render the card.

import os

import customtkinter as ctk

from core import theme

REFRESH_MS = 1000


class MusicMiniWidget(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color="transparent")
        self.manager = manager

        self.grid_columnconfigure(0, weight=1)

        self.track_label = ctk.CTkLabel(
            self,
            text="Nothing playing",
            font=theme.font(11),
            text_color=theme.MUTED,
            anchor="w"
        )
        self.track_label.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        self.progress = ctk.CTkProgressBar(
            self,
            height=6,
            corner_radius=3,
            fg_color=theme.PANEL_2,
            progress_color=theme.ACCENT
        )
        self.progress.set(0)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.grid(row=2, column=0, sticky="w")

        btn_kw = dict(
            width=30, height=26,
            fg_color=theme.PANEL_2,
            hover_color=theme.PANEL_HOVER,
            text_color=theme.TEXT,
            corner_radius=6,
            font=theme.font(12)
        )

        self.prev_btn = ctk.CTkButton(controls, text="⏮", command=self._prev, **btn_kw)
        self.prev_btn.pack(side="left", padx=(0, 4))

        self.play_btn = ctk.CTkButton(controls, text="▶", command=self._toggle_play, **btn_kw)
        self.play_btn.pack(side="left", padx=(0, 4))

        self.next_btn = ctk.CTkButton(controls, text="⏭", command=self._next, **btn_kw)
        self.next_btn.pack(side="left")

        self._set_controls_enabled(False)
        self._tick()

    # ── engine access ────────────────────────────────────────

    def _engine(self):
        return getattr(self.manager, "music_engine", None)

    # ── controls ─────────────────────────────────────────────

    def _set_controls_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        for b in (self.prev_btn, self.play_btn, self.next_btn):
            b.configure(state=state)

    def _toggle_play(self):
        engine = self._engine()
        if engine:
            engine.pause()  # engine.pause() toggles play/pause, see player.py

    def _next(self):
        engine = self._engine()
        if engine:
            engine.next()

    def _prev(self):
        engine = self._engine()
        if engine:
            engine.prev()

    # ── refresh loop ─────────────────────────────────────────

    def _tick(self):
        if not self.winfo_exists():
            return

        try:
            engine = self._engine()

            if engine is None or engine.index < 0 or not engine.playlist:
                self.track_label.configure(text="Nothing playing")
                self.progress.set(0)
                self._set_controls_enabled(engine is not None and bool(engine.playlist))
                self.play_btn.configure(text="▶")
            else:
                self._set_controls_enabled(True)

                name = os.path.basename(engine.playlist[engine.index])
                if len(name) > 30:
                    name = name[:27] + "..."
                self.track_label.configure(text=name, text_color=theme.TEXT)

                is_playing = engine.is_playing()
                self.play_btn.configure(text="⏸" if is_playing else "▶")

                length = engine.get_length()
                pos = engine.get_time()
                self.progress.set((pos / length) if length else 0)
        except Exception:
            pass

        self.after(REFRESH_MS, self._tick)


def build(parent, manager):
    return MusicMiniWidget(parent, manager)
