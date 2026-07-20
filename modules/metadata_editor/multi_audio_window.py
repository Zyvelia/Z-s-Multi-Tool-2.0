# modules/metadata_editor/multi_audio_window.py
#
# Popout window (opened via "Batch Edit..." on the Audio Tags tab) for
# tagging many audio files at once — e.g. a freshly ripped album where
# every track shares Artist/Album/Genre/Year but has its own Title.
#
# Bulk fields are apply-if-filled: leave a field blank and it's left
# alone on every file. Track numbers can optionally be auto-numbered in
# list order instead of typed in per file.

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
            height=32, corner_radius=8)
_BTN_ACCENT = dict(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="white",
                    height=32, corner_radius=8)
_BTN_DANGER = dict(fg_color=PANEL_2, hover_color=DANGER_HOVER, text_color=TEXT,
                    height=32, corner_radius=8)

# Bulk fields exclude Title (near-always unique per track) and Track #
# (handled separately via the auto-number control below).
BULK_FIELDS = [(k, l) for k, l in backend.TAG_FIELDS if k not in ("title", "tracknumber")]


def _make_btn(parent, text, cmd, **overrides):
    kw = {**_BTN, **overrides}
    return ctk.CTkButton(parent, text=text, command=cmd, **kw)


class _FileRow(ctk.CTkFrame):
    """One row in the batch list: checkbox + filename + short tag preview."""

    def __init__(self, parent, path, on_toggle):
        super().__init__(parent, fg_color=PANEL_2, corner_radius=6)
        self.path = path
        self.audio_obj = None
        self.kind = None

        self.grid_columnconfigure(1, weight=1)

        self.selected = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self, text="", variable=self.selected, width=20,
                         command=on_toggle, fg_color=ACCENT, hover_color=ACCENT_HOVER
                         ).grid(row=0, column=0, rowspan=2, padx=(8, 4), pady=6)

        self.name_label = ctk.CTkLabel(self, text=os.path.basename(path), text_color=TEXT, anchor="w")
        self.name_label.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=(6, 0))

        self.preview_label = ctk.CTkLabel(self, text="Loading...", text_color=MUTED, anchor="w", font=theme.font(11))
        self.preview_label.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(0, 6))

        self._try_load()

    def _try_load(self):
        try:
            self.audio_obj, self.kind = backend.load_audio(self.path)
            artist = backend.get_field_value(self.audio_obj, self.kind, "artist")
            title = backend.get_field_value(self.audio_obj, self.kind, "title")
            preview = f"{artist} - {title}" if artist or title else "(no tags)"
            self.preview_label.configure(text=preview, text_color=MUTED)
        except Exception as e:
            self.preview_label.configure(text=f"Failed to read: {e}", text_color=DANGER)
            self.audio_obj = None
            self.kind = None


class MultiAudioWindow(ctk.CTkToplevel):

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Batch Audio Tag Editor")
        self.geometry("760x540")
        self.configure(fg_color=BG)
        self.minsize(640, 420)

        self.rows = []  # list of _FileRow

        self._build_ui()

        if not backend.MUTAGEN_AVAILABLE:
            self._set_status("mutagen is not installed. Run: pip install mutagen", error=True)

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(1, weight=1)

        # --- top bar ---
        top = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 6))

        _make_btn(top, "Add Files...", self._add_files, **_BTN_ACCENT).pack(side="left", padx=(10, 6), pady=10)
        _make_btn(top, "Add Folder...", self._add_folder).pack(side="left", padx=6, pady=10)
        _make_btn(top, "Clear List", self._clear_list, **_BTN_DANGER).pack(side="left", padx=6, pady=10)
        self.count_label = ctk.CTkLabel(top, text="0 files", text_color=MUTED)
        self.count_label.pack(side="right", padx=10)

        # --- left: scrollable file list ---
        list_panel = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        list_panel.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=6)
        list_panel.grid_columnconfigure(0, weight=1)
        list_panel.grid_rowconfigure(1, weight=1)

        select_row = ctk.CTkFrame(list_panel, fg_color="transparent")
        select_row.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        _make_btn(select_row, "Select All", self._select_all, height=26).pack(side="left", padx=(0, 6))
        _make_btn(select_row, "Select None", self._select_none, height=26).pack(side="left")

        self.list_frame = ctk.CTkScrollableFrame(list_panel, fg_color="transparent")
        self.list_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.list_frame.grid_columnconfigure(0, weight=1)

        # --- right: bulk edit panel (scrollable so it never gets clipped
        # as fields are added) ---
        edit_panel = ctk.CTkScrollableFrame(
            self, fg_color=PANEL, corner_radius=10, width=260,
            scrollbar_button_color=PANEL_2, scrollbar_button_hover_color=PANEL_HOVER,
        )
        edit_panel.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=6)

        ctk.CTkLabel(edit_panel, text="Apply to Selected", text_color=TEXT, font=theme.font(13)).pack(
            padx=14, pady=(14, 4), anchor="w")
        ctk.CTkLabel(edit_panel, text="Blank fields are left unchanged.", text_color=MUTED,
                     font=theme.font(11)).pack(padx=14, pady=(0, 10), anchor="w")

        self.field_vars = {}
        for key, label in BULK_FIELDS:
            ctk.CTkLabel(edit_panel, text=label, text_color=MUTED, anchor="w").pack(padx=14, pady=(4, 0), anchor="w")
            var = ctk.StringVar()
            ctk.CTkEntry(edit_panel, fg_color=PANEL_2, border_color=PANEL_2, textvariable=var).pack(
                padx=14, pady=(2, 0), fill="x")
            self.field_vars[key] = var

        # --- auto-number track field ---
        track_row = ctk.CTkFrame(edit_panel, fg_color="transparent")
        track_row.pack(padx=14, pady=(14, 0), fill="x")
        self.auto_number = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(track_row, text="Auto-number tracks, starting at:", variable=self.auto_number,
                         fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=TEXT,
                         font=theme.font(11)).pack(anchor="w")
        self.track_start_var = ctk.StringVar(value="1")
        ctk.CTkEntry(edit_panel, fg_color=PANEL_2, border_color=PANEL_2, width=60,
                     textvariable=self.track_start_var).pack(padx=14, pady=(4, 0), anchor="w")
        ctk.CTkLabel(edit_panel, text="Numbers assigned in list order, top to bottom.",
                     text_color=MUTED, font=theme.font(10), justify="left", wraplength=220).pack(
            padx=14, pady=(2, 0), anchor="w")

        # --- cover art ---
        ctk.CTkLabel(edit_panel, text="Cover Art", text_color=TEXT, font=theme.font(13)).pack(
            padx=14, pady=(20, 4), anchor="w")
        _make_btn(edit_panel, "Set Cover for Selected...", self._pick_cover_for_all).pack(padx=14, pady=4, fill="x")
        _make_btn(edit_panel, "Remove Cover from Selected", self._remove_cover_for_all, **_BTN_DANGER).pack(
            padx=14, pady=4, fill="x")
        self._bulk_cover_path = None

        # --- apply / close ---
        _make_btn(edit_panel, "Apply to Selected", self._apply_to_selected, **_BTN_ACCENT).pack(
            padx=14, pady=(20, 4), fill="x")
        _make_btn(edit_panel, "Close", self.destroy).pack(padx=14, pady=4, fill="x")

        # --- status bar ---
        self.status_label = ctk.CTkLabel(self, text="", text_color=MUTED, anchor="w")
        self.status_label.grid(row=2, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 10))

    def _set_status(self, msg, error=False):
        self.status_label.configure(text=msg, text_color=(DANGER if error else MUTED))

    def _update_count(self):
        self.count_label.configure(text=f"{len(self.rows)} files")

    # ------------------------------------------------------------- list

    def _add_files(self):
        if not backend.MUTAGEN_AVAILABLE:
            return
        paths = filedialog.askopenfilenames(
            title="Select audio files",
            filetypes=[("Audio files", " ".join(f"*{e}" for e in backend.AUDIO_EXTS)), ("All files", "*.*")])
        self._add_paths(paths)

    def _add_folder(self):
        if not backend.MUTAGEN_AVAILABLE:
            return
        folder = filedialog.askdirectory(title="Select folder")
        if not folder:
            return
        found = []
        for root, _dirs, files in os.walk(folder):
            for name in files:
                if os.path.splitext(name)[1].lower() in backend.AUDIO_EXTS:
                    found.append(os.path.join(root, name))
        found.sort()
        self._add_paths(found)

    def _add_paths(self, paths):
        existing = {row.path for row in self.rows}
        added = 0
        for path in paths:
            if path in existing:
                continue
            row = _FileRow(self.list_frame, path, on_toggle=lambda: None)
            row.pack(fill="x", pady=3)
            self.rows.append(row)
            added += 1
        self._update_count()
        if added:
            self._set_status(f"Added {added} file(s).")

    def _clear_list(self):
        for row in self.rows:
            row.destroy()
        self.rows = []
        self._update_count()
        self._set_status("List cleared.")

    def _select_all(self):
        for row in self.rows:
            row.selected.set(True)

    def _select_none(self):
        for row in self.rows:
            row.selected.set(False)

    def _selected_rows(self):
        return [row for row in self.rows if row.selected.get() and row.audio_obj is not None]

    # ---------------------------------------------------------- cover

    def _pick_cover_for_all(self):
        path = filedialog.askopenfilename(title="Select cover image",
                                           filetypes=[("Images", "*.jpg *.jpeg *.png"), ("All files", "*.*")])
        if path:
            self._bulk_cover_path = path
            self._set_status(f"Cover queued: {os.path.basename(path)} (applies on 'Apply to Selected')")

    def _remove_cover_for_all(self):
        self._bulk_cover_path = ""  # marker: strip on apply
        self._set_status("Cover removal queued (applies on 'Apply to Selected')")

    # ---------------------------------------------------------- apply

    def _apply_to_selected(self):
        selected = self._selected_rows()
        if not selected:
            self._set_status("No files selected.", error=True)
            return

        auto_number = self.auto_number.get()
        try:
            start_num = int(self.track_start_var.get().strip() or "1")
        except ValueError:
            self._set_status("Track start number must be an integer.", error=True)
            return

        errors = []
        for i, row in enumerate(selected):
            try:
                for key, var in self.field_vars.items():
                    value = var.get().strip()
                    if value:
                        backend.set_field_value(row.audio_obj, row.kind, key, value)

                if auto_number:
                    backend.set_field_value(row.audio_obj, row.kind, "tracknumber", str(start_num + i))

                backend.save_audio(row.audio_obj)

                if self._bulk_cover_path == "":
                    backend.strip_cover(row.path, row.kind)
                elif self._bulk_cover_path:
                    backend.embed_cover(row.path, row.kind, self._bulk_cover_path)

                row._try_load()  # refresh preview text
            except Exception as e:
                errors.append(f"{os.path.basename(row.path)}: {e}")

        self._bulk_cover_path = None

        if errors:
            self._set_status(f"Applied with {len(errors)} error(s) — see popup.", error=True)
            messagebox.showerror("Batch Audio Tag Editor", "Some files failed:\n\n" + "\n".join(errors))
        else:
            self._set_status(f"Applied to {len(selected)} file(s) successfully.")
