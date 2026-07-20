# modules/metadata_editor/audio_tab.py
#
# Single-file audio tag + cover art editor. "Batch Edit..." opens
# multi_audio_window.py as a popout Toplevel for editing many files at
# once, rather than adding another top-level tab.
#
# Dependency: pip install mutagen

import io
import os

import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image

from core import theme
from . import audio_backend as backend

BG = theme.BG
PANEL = theme.PANEL
PANEL_2 = theme.PANEL_2
ACCENT = theme.ACCENT
ACCENT_HOVER = theme.ACCENT_HOVER
TEXT = theme.TEXT
MUTED = theme.MUTED
DANGER = theme.DANGER
DANGER_HOVER = theme.DANGER_HOVER
PANEL_HOVER = theme.PANEL_HOVER

_BTN = dict(fg_color=PANEL_2, hover_color=PANEL_HOVER, text_color=TEXT,
            height=34, corner_radius=8)
_BTN_ACCENT = dict(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="white",
                    height=34, corner_radius=8)
_BTN_DANGER = dict(fg_color=PANEL_2, hover_color=DANGER_HOVER, text_color=TEXT,
                    height=34, corner_radius=8)

TAG_FIELDS = backend.TAG_FIELDS


def _make_btn(parent, text, cmd, **overrides):
    kw = {**_BTN, **overrides}
    return ctk.CTkButton(parent, text=text, command=cmd, **kw)


class AudioTagsTab(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color="transparent")
        self.manager = manager

        self.current_path = None
        self.current_audio = None
        self.current_kind = None
        self.field_vars = {}
        self.cover_image_path = None
        self._cover_ctk_image = None
        self._batch_window = None  # keep single instance of the popout

        self._build_ui()

        if not backend.MUTAGEN_AVAILABLE:
            self._set_status("mutagen is not installed. Run: pip install mutagen", error=True)
            self._set_controls_enabled(False)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=2, pady=(2, 6))
        top.grid_columnconfigure(1, weight=1)

        _make_btn(top, "Open File", self._open_file, width=110, **_BTN_ACCENT).grid(
            row=0, column=0, padx=10, pady=10)
        self.path_label = ctk.CTkLabel(top, text="No file loaded", text_color=MUTED, anchor="w")
        self.path_label.grid(row=0, column=1, sticky="ew", padx=6, pady=10)
        _make_btn(top, "Batch Edit...", self._open_batch_window, width=120).grid(
            row=0, column=2, padx=10, pady=10)

        fields_panel = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        fields_panel.grid(row=1, column=0, sticky="nsew", padx=(2, 6), pady=2)
        fields_panel.grid_columnconfigure(1, weight=1)

        for i, (key, label) in enumerate(TAG_FIELDS):
            ctk.CTkLabel(fields_panel, text=label, width=100, anchor="w", text_color=TEXT).grid(
                row=i, column=0, padx=(14, 6), pady=8, sticky="w")
            var = ctk.StringVar()
            entry = ctk.CTkEntry(fields_panel, fg_color=PANEL_2, border_color=PANEL_2, textvariable=var)
            entry.grid(row=i, column=1, padx=(0, 14), pady=8, sticky="ew")
            self.field_vars[key] = var

        side_panel = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10, width=220)
        side_panel.grid(row=1, column=1, sticky="ns", padx=(6, 2), pady=2)
        side_panel.grid_propagate(False)

        ctk.CTkLabel(side_panel, text="Cover Art", text_color=MUTED).pack(pady=(14, 6))
        self.cover_frame = ctk.CTkLabel(side_panel, text="No\nCover", width=180, height=180,
                                         fg_color=PANEL_2, corner_radius=8, text_color=MUTED)
        self.cover_frame.pack(padx=14, pady=6)

        _make_btn(side_panel, "Set Cover Image...", self._pick_cover).pack(padx=14, pady=(10, 4), fill="x")
        _make_btn(side_panel, "Remove Cover", self._remove_cover, **_BTN_DANGER).pack(padx=14, pady=4, fill="x")
        _make_btn(side_panel, "Save Changes", self._save_changes, **_BTN_ACCENT).pack(padx=14, pady=(20, 6), fill="x")
        _make_btn(side_panel, "Reload / Discard", self._reload_current).pack(padx=14, pady=4, fill="x")

        self.side_panel = side_panel
        self.fields_panel = fields_panel

        self.status_label = ctk.CTkLabel(self, text="", text_color=MUTED, anchor="w")
        self.status_label.grid(row=2, column=0, columnspan=2, sticky="ew", padx=4, pady=(6, 2))

        self._set_controls_enabled(False)

    def _open_batch_window(self):
        # Lazy import avoids paying multi_audio_window's import cost until
        # someone actually clicks the button.
        from .multi_audio_window import MultiAudioWindow

        if self._batch_window is not None and self._batch_window.winfo_exists():
            self._batch_window.focus()
            return
        self._batch_window = MultiAudioWindow(self)

    def _set_controls_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for child in self.fields_panel.winfo_children():
            if isinstance(child, ctk.CTkEntry):
                child.configure(state=state)
        for child in self.side_panel.winfo_children():
            if isinstance(child, ctk.CTkButton):
                child.configure(state=state)

    def _set_status(self, msg, error=False):
        self.status_label.configure(text=msg, text_color=(DANGER if error else MUTED))

    def _open_file(self):
        if not backend.MUTAGEN_AVAILABLE:
            return
        path = filedialog.askopenfilename(
            title="Select audio file",
            filetypes=[("Audio files", " ".join(f"*{e}" for e in backend.AUDIO_EXTS)), ("All files", "*.*")])
        if path:
            self._load_file(path)

    def _load_file(self, path):
        try:
            audio_obj, kind = backend.load_audio(path)
            self.current_audio = audio_obj
            self.current_kind = kind
            self.current_path = path
            self.cover_image_path = None
            self.path_label.configure(text=os.path.basename(path))
            self._populate_fields()
            self._populate_cover()
            self._set_controls_enabled(True)
            self._set_status("Loaded successfully.")
        except Exception as e:
            self._set_status(f"Failed to load file: {e}", error=True)
            messagebox.showerror("Metadata Editor", f"Could not load file:\n{e}")

    def _reload_current(self):
        if self.current_path:
            self._load_file(self.current_path)

    def _populate_fields(self):
        for key, var in self.field_vars.items():
            value = backend.get_field_value(self.current_audio, self.current_kind, key) if self.current_audio else ""
            var.set(value)

    def _populate_cover(self):
        self._cover_ctk_image = None
        self.cover_frame.configure(image=None, text="No\nCover")
        art_bytes = backend.extract_cover_bytes(self.current_path, self.current_kind, self.current_audio)
        if art_bytes:
            self._show_cover_bytes(art_bytes)

    def _show_cover_bytes(self, data: bytes):
        try:
            img = Image.open(io.BytesIO(data))
            img.thumbnail((180, 180))
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            self._cover_ctk_image = ctk_img
            self.cover_frame.configure(image=ctk_img, text="")
        except Exception:
            self.cover_frame.configure(image=None, text="Cover\n(unreadable)")

    def _pick_cover(self):
        if not self.current_path:
            return
        path = filedialog.askopenfilename(title="Select cover image",
                                           filetypes=[("Images", "*.jpg *.jpeg *.png"), ("All files", "*.*")])
        if not path:
            return
        self.cover_image_path = path
        try:
            img = Image.open(path)
            img.thumbnail((180, 180))
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            self._cover_ctk_image = ctk_img
            self.cover_frame.configure(image=ctk_img, text="")
        except Exception as e:
            self._set_status(f"Could not preview image: {e}", error=True)

    def _remove_cover(self):
        self.cover_image_path = ""
        self._cover_ctk_image = None
        self.cover_frame.configure(image=None, text="No\nCover")

    def _save_changes(self):
        if not self.current_path or self.current_audio is None:
            return
        try:
            for key, var in self.field_vars.items():
                backend.set_field_value(self.current_audio, self.current_kind, key, var.get().strip())
            backend.save_audio(self.current_audio)

            if self.cover_image_path == "":
                backend.strip_cover(self.current_path, self.current_kind)
            elif self.cover_image_path:
                backend.embed_cover(self.current_path, self.current_kind, self.cover_image_path)

            self.cover_image_path = None
            self._set_status("Saved successfully.")
        except Exception as e:
            self._set_status(f"Save failed: {e}", error=True)
            messagebox.showerror("Metadata Editor", f"Could not save changes:\n{e}")
