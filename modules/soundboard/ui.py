import customtkinter as ctk
from tkinter import filedialog
import os
import threading
import numpy as np

from core import theme

# ── Colours (shared app theme) ────────────────────────────────────────────
BG      = theme.BG
PANEL   = theme.PANEL
PANEL_2 = theme.PANEL_2
ACCENT  = theme.ACCENT
DANGER  = theme.DANGER
SUCCESS = theme.SUCCESS
TEXT    = theme.TEXT
MUTED   = theme.MUTED

_BTN        = dict(fg_color=PANEL_2, hover_color=ACCENT,      text_color=TEXT,   height=34, corner_radius=8)
_BTN_ACCENT = dict(fg_color=ACCENT,  hover_color=theme.ACCENT_DIM,   text_color="white", height=34, corner_radius=8)
_BTN_DANGER = dict(fg_color=DANGER,  hover_color=theme.DANGER_HOVER,   text_color="white", height=34, corner_radius=8)

def _make_btn(parent, text, cmd, **ov):
    return ctk.CTkButton(parent, text=text, command=cmd, **{**_BTN, **ov})

AUDIO_EXT = (".mp3", ".wav", ".flac", ".ogg", ".m4a")
GRID_COLS  = 4


# ── Audio helpers ─────────────────────────────────────────────────────────────

def _get_output_devices() -> list[dict]:
    """Return list of {index, name} for every output-capable device."""
    try:
        import sounddevice as sd
        devs = []
        for i, d in enumerate(sd.query_devices()):
            if d["max_output_channels"] > 0:
                devs.append({"index": i, "name": d["name"]})
        return devs
    except Exception as e:
        print(f"[Soundboard] sounddevice not available: {e}")
        return []


def _load_audio_numpy(path: str):
    """
    Load any audio file → (samples_float32 shape [N,2], samplerate).
    Uses ffmpeg via subprocess for MP3/M4A so pydub/pyaudioop are not needed.
    Returns (None, 0) on failure.
    """
    # Strip accidental double extension e.g. song.mp3.mp3
    while True:
        base, ext = os.path.splitext(path)
        if base.lower().endswith(ext.lower()) and ext:
            path = base   # e.g. song.mp3.mp3 → song.mp3
        else:
            break
    ext = os.path.splitext(path)[1].lower()

    try:
        import soundfile as sf
        import subprocess, tempfile

        # For formats soundfile can't read natively, decode via ffmpeg to a temp WAV.
        # Copy source to a plain ASCII temp path first so special chars in the
        # filename (e.g. ⧸) don't trip up ffmpeg on Windows.
        if ext in (".mp3", ".m4a", ".ogg", ".flac"):
            import shutil
            tmp_in  = tempfile.NamedTemporaryFile(suffix=ext,   delete=False)
            tmp_out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp_in.close()
            tmp_out.close()
            try:
                shutil.copy2(path, tmp_in.name)
                subprocess.run(
                    ["ffmpeg", "-y", "-i", tmp_in.name, "-ar", "44100",
                     "-ac", "2", "-f", "wav", tmp_out.name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
                )
                data, sr = sf.read(tmp_out.name, dtype="float32", always_2d=True)
            finally:
                for f in (tmp_in.name, tmp_out.name):
                    try:
                        os.unlink(f)
                    except Exception:
                        pass
        else:
            data, sr = sf.read(path, dtype="float32", always_2d=True)

        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        return data, sr

    except Exception as e:
        print(f"[Soundboard] Failed to load {path}: {e}")
        return None, 0


def _play_on_device(samples, samplerate: int, device_index: int, volume: float):
    """Play a numpy audio array on a specific sounddevice output device."""
    try:
        import sounddevice as sd
        out = (samples * volume).astype(np.float32)
        sd.play(out, samplerate=samplerate, device=device_index, blocking=False)
    except Exception as e:
        print(f"[Soundboard] Playback error on device {device_index}: {e}")


# ── Sound slot ────────────────────────────────────────────────────────────────

class SoundSlot:
    def __init__(self, path: str, volume: float = 1.0):
        self.path    = path
        self.name    = os.path.splitext(os.path.basename(path))[0]
        self.volume  = volume
        self._samples   = None
        self._samplerate = 0
        self._load()

    def _load(self):
        self._samples, self._samplerate = _load_audio_numpy(self.path)

    def play(self, device_indices: list[int]):
        if self._samples is None:
            return
        for idx in device_indices:
            threading.Thread(
                target=_play_on_device,
                args=(self._samples, self._samplerate, idx, self.volume),
                daemon=True
            ).start()

    def stop_all(self):
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass

    def set_volume(self, v: float):
        self.volume = max(0.0, min(1.0, float(v)))


# ── Soundboard page ───────────────────────────────────────────────────────────

class SoundboardPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=BG)
        self.manager        = manager
        self.slots: list[SoundSlot] = []
        self._master_volume = 1.0

        # Two selected output device indices (None = system default)
        self._device_a: int | None = None   # e.g. headphones / audio card
        self._device_b: int | None = None   # e.g. Voicemeeter Virtual Input

        self._all_devices: list[dict] = []

        self._build_ui()
        self._refresh_devices()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()
        self._build_toolbar()
        self._build_device_bar()
        self._build_board()

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        header.pack(fill="x", padx=12, pady=(12, 4))

        ctk.CTkLabel(header, text="🔊  Soundboard",
                     font=("Segoe UI", 22, "bold"), text_color=TEXT
                     ).pack(side="left", padx=14, pady=10)

        self.status = ctk.CTkLabel(header, text="No sounds loaded", text_color=MUTED)
        self.status.pack(side="right", padx=14)

    def _build_toolbar(self):
        bar = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        bar.pack(fill="x", padx=12, pady=(0, 4))

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=8)

        _make_btn(inner, "＋ Add Files",  self._add_files,  **_BTN_ACCENT).pack(side="left", padx=(0, 6))
        _make_btn(inner, "📁 Load Folder", self._load_folder).pack(side="left", padx=(0, 6))
        _make_btn(inner, "🗑  Clear All",  self._clear_all,  **_BTN_DANGER).pack(side="left", padx=(0, 18))
        _make_btn(inner, "⏹  Stop All",   self._stop_all,
                  fg_color="#4a2060", hover_color="#6a30a0").pack(side="left")

        ctk.CTkLabel(inner, text="Master Vol", text_color=MUTED,
                     font=("Segoe UI", 11)).pack(side="right", padx=(12, 4))
        self._master_slider = ctk.CTkSlider(
            inner, from_=0, to=1, width=120,
            progress_color=ACCENT, command=self._set_master_volume)
        self._master_slider.set(1.0)
        self._master_slider.pack(side="right")

    def _build_device_bar(self):
        bar = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        bar.pack(fill="x", padx=12, pady=(0, 4))

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=10)

        # ── Device A (headphones / audio card) ──
        col_a = ctk.CTkFrame(inner, fg_color="transparent")
        col_a.pack(side="left", padx=(0, 16))

        ctk.CTkLabel(col_a, text="🎧  You hear (audio card)",
                     text_color=MUTED, font=("Segoe UI", 11)
                     ).pack(anchor="w", pady=(0, 4))

        self._device_a_var = ctk.StringVar(value="Default")
        self._device_a_menu = ctk.CTkOptionMenu(
            col_a, variable=self._device_a_var,
            values=["Default"],
            fg_color=PANEL_2, button_color=ACCENT,
            button_hover_color="#2f7fd6", text_color=TEXT,
            command=lambda v: self._on_device_pick("a", v),
            width=260)
        self._device_a_menu.pack()

        # ── Device B (Voicemeeter) ──
        col_b = ctk.CTkFrame(inner, fg_color="transparent")
        col_b.pack(side="left", padx=(0, 16))

        ctk.CTkLabel(col_b, text="🎙  Mic output (Voicemeeter)",
                     text_color=MUTED, font=("Segoe UI", 11)
                     ).pack(anchor="w", pady=(0, 4))

        self._device_b_var = ctk.StringVar(value="None")
        self._device_b_menu = ctk.CTkOptionMenu(
            col_b, variable=self._device_b_var,
            values=["None"],
            fg_color=PANEL_2, button_color="#4a2060",
            button_hover_color="#6a30a0", text_color=TEXT,
            command=lambda v: self._on_device_pick("b", v),
            width=260)
        self._device_b_menu.pack()

        # ── Refresh ──
        col_r = ctk.CTkFrame(inner, fg_color="transparent")
        col_r.pack(side="left")

        _make_btn(col_r, "↺ Refresh", self._refresh_devices, width=90).pack(pady=(18, 0))

    def _build_board(self):
        container = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        container.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        top = ctk.CTkFrame(container, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 4))

        ctk.CTkLabel(top, text="Sounds",
                     font=("Segoe UI", 15, "bold"), text_color=TEXT).pack(side="left")
        self._count_label = ctk.CTkLabel(top, text="0 sounds", text_color=MUTED)
        self._count_label.pack(side="right")

        self._grid_frame = ctk.CTkScrollableFrame(
            container, fg_color=PANEL_2, corner_radius=8)
        self._grid_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        for c in range(GRID_COLS):
            self._grid_frame.columnconfigure(c, weight=1, uniform="col")

        self._show_empty()

    # ── Device helpers ────────────────────────────────────────────────────────

    def _refresh_devices(self):
        self._all_devices = _get_output_devices()
        names_a = ["Default"] + [d["name"] for d in self._all_devices]
        names_b = ["None"]    + [d["name"] for d in self._all_devices]

        self._device_a_menu.configure(values=names_a)
        self._device_b_menu.configure(values=names_b)

        # Auto-select Voicemeeter for device B if found
        for d in self._all_devices:
            if "voicemeeter" in d["name"].lower() and "input" in d["name"].lower():
                self._device_b_var.set(d["name"])
                self._device_b = d["index"]
                break

        self.status.configure(text=f"Found {len(self._all_devices)} output devices")

    def _on_device_pick(self, slot: str, name: str):
        idx = None
        if name not in ("Default", "None"):
            for d in self._all_devices:
                if d["name"] == name:
                    idx = d["index"]
                    break
        if slot == "a":
            self._device_a = idx
        else:
            self._device_b = idx

    def _active_device_indices(self) -> list[int]:
        """Return list of device indices to play to. Deduped, None = default (0)."""
        import sounddevice as sd
        default_idx = sd.default.device[1] if sd.default.device[1] is not None else 0

        a = self._device_a if self._device_a is not None else default_idx
        b = self._device_b

        if b is None:
            return [a]
        if a == b:
            return [a]
        return [a, b]

    # ── Load sounds ───────────────────────────────────────────────────────────

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            filetypes=[("Audio Files", "*.mp3 *.wav *.flac *.ogg *.m4a")])
        if paths:
            self._add_slots([p for p in paths if p not in {s.path for s in self.slots}])

    def _load_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        existing = {s.path for s in self.slots}
        new_paths = sorted(
            os.path.join(root, f)
            for root, _dirs, files in os.walk(folder)
            for f in files
            if f.lower().endswith(AUDIO_EXT)
        )
        new_paths = [p for p in new_paths if p not in existing]
        if not new_paths:
            self.status.configure(text="No new audio files found")
            return
        self._add_slots(new_paths)

    def _add_slots(self, paths: list[str]):
        self.status.configure(text=f"Loading {len(paths)} sound(s)…")
        def _worker():
            new_slots = [SoundSlot(p, self._master_volume) for p in paths]
            self.after(0, lambda: self._append_slots(new_slots))
        threading.Thread(target=_worker, daemon=True).start()

    def _append_slots(self, new_slots: list[SoundSlot]):
        self.slots.extend(new_slots)
        self._rebuild_grid()
        self._update_count()

    # ── Grid ─────────────────────────────────────────────────────────────────

    def _show_empty(self):
        lbl = ctk.CTkLabel(
            self._grid_frame,
            text="No sounds yet.\nUse  ＋ Add Files  or  📁 Load Folder  above.",
            text_color=MUTED, font=("Segoe UI", 13), justify="center")
        lbl.grid(row=0, column=0, columnspan=GRID_COLS, pady=60, padx=20)

    def _rebuild_grid(self):
        for w in self._grid_frame.winfo_children():
            w.destroy()
        if not self.slots:
            self._show_empty()
            return
        for i, slot in enumerate(self.slots):
            row, col = divmod(i, GRID_COLS)
            self._make_sound_card(slot, i, row, col)

    def _make_sound_card(self, slot: SoundSlot, idx: int, row: int, col: int):
        card = ctk.CTkFrame(self._grid_frame, fg_color=PANEL,
                            corner_radius=10, border_width=1, border_color=PANEL_2)
        card.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")

        ctk.CTkLabel(card, text=slot.name,
                     font=("Segoe UI", 11, "bold"), text_color=TEXT,
                     wraplength=160, anchor="center", justify="center"
                     ).pack(padx=8, pady=(10, 4))

        ctk.CTkButton(card, text="▶  Play",
                      fg_color=SUCCESS, hover_color="#27ae60",
                      text_color="white", height=38, corner_radius=8,
                      font=("Segoe UI", 13, "bold"),
                      command=lambda s=slot: self._play_sound(s)
                      ).pack(fill="x", padx=10, pady=(2, 2))

        ctk.CTkButton(card, text="⏹  Stop",
                      fg_color=PANEL_2, hover_color=DANGER,
                      text_color=MUTED, height=30, corner_radius=8,
                      command=lambda s=slot: s.stop_all()
                      ).pack(fill="x", padx=10, pady=(0, 4))

        vol_row = ctk.CTkFrame(card, fg_color="transparent")
        vol_row.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkLabel(vol_row, text="Vol", text_color=MUTED,
                     font=("Segoe UI", 10)).pack(side="left", padx=(0, 4))
        sl = ctk.CTkSlider(vol_row, from_=0, to=1,
                           progress_color=ACCENT, height=14,
                           command=lambda v, s=slot: s.set_volume(v))
        sl.set(slot.volume)
        sl.pack(side="left", fill="x", expand=True)

        ctk.CTkButton(card, text="✕ Remove",
                      fg_color="transparent", hover_color=DANGER,
                      text_color=MUTED, height=24, corner_radius=6,
                      font=("Segoe UI", 10),
                      command=lambda i=idx: self._remove_slot(i)
                      ).pack(pady=(0, 8))

    # ── Playback ──────────────────────────────────────────────────────────────

    def _play_sound(self, slot: SoundSlot):
        try:
            devices = self._active_device_indices()
        except Exception:
            devices = [None]
        threading.Thread(target=slot.play, args=(devices,), daemon=True).start()
        self.status.configure(text=f"▶ {slot.name}")

    def _stop_all(self):
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        self.status.configure(text="All sounds stopped")

    # ── Master volume ─────────────────────────────────────────────────────────

    def _set_master_volume(self, value: float):
        self._master_volume = float(value)
        for slot in self.slots:
            slot.set_volume(self._master_volume)

    # ── Misc ──────────────────────────────────────────────────────────────────

    def _remove_slot(self, idx: int):
        if 0 <= idx < len(self.slots):
            del self.slots[idx]
            self._rebuild_grid()
            self._update_count()

    def _clear_all(self):
        self._stop_all()
        self.slots.clear()
        self._rebuild_grid()
        self._update_count()
        self.status.configure(text="Board cleared")

    def _update_count(self):
        n = len(self.slots)
        self._count_label.configure(text=f"{n} {'sound' if n == 1 else 'sounds'}")
        self.status.configure(text=f"{n} sound(s) ready" if n else "No sounds loaded")

    def on_leave(self):
        self._stop_all()