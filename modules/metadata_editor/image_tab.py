# modules/metadata_editor/image_tab.py
#
# Edits common top-level EXIF fields on JPEG/PNG/TIFF via Pillow.
# Image.getexif() / save(exif=...) is one code path across all three
# formats (APP1 for JPEG, eXIf chunk for PNG, IFD0 for TIFF), so no
# separate piexif dependency is needed.

import os

import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image

from core import theme

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

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff")

# Standard top-level EXIF tag IDs. GPS and maker-note data are left alone —
# those live in nested IFDs and aren't worth the edit-footgun risk here.
EXIF_FIELDS = [
    (0x010E, "ImageDescription"),
    (0x013B, "Artist"),
    (0x8298, "Copyright"),
    (0x010F, "Make"),
    (0x0110, "Model"),
    (0x0131, "Software"),
    (0x0132, "DateTime"),
]


def _make_btn(parent, text, cmd, **overrides):
    kw = {**_BTN, **overrides}
    return ctk.CTkButton(parent, text=text, command=cmd, **kw)


class ImageExifTab(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color="transparent")
        self.manager = manager

        self.current_path = None
        self.field_vars = {}
        self._preview_ctk_image = None

        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=2, pady=(2, 6))
        top.grid_columnconfigure(1, weight=1)

        _make_btn(top, "Open Image", self._open_file, width=110, **_BTN_ACCENT).grid(
            row=0, column=0, padx=10, pady=10)
        self.path_label = ctk.CTkLabel(top, text="No file loaded", text_color=MUTED, anchor="w")
        self.path_label.grid(row=0, column=1, sticky="ew", padx=6, pady=10)

        fields_panel = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        fields_panel.grid(row=1, column=0, sticky="nsew", padx=(2, 6), pady=2)
        fields_panel.grid_columnconfigure(1, weight=1)

        for i, (tag_id, label) in enumerate(EXIF_FIELDS):
            ctk.CTkLabel(fields_panel, text=label, width=120, anchor="w", text_color=TEXT).grid(
                row=i, column=0, padx=(14, 6), pady=8, sticky="w")
            var = ctk.StringVar()
            entry = ctk.CTkEntry(fields_panel, fg_color=PANEL_2, border_color=PANEL_2, textvariable=var)
            entry.grid(row=i, column=1, padx=(0, 14), pady=8, sticky="ew")
            self.field_vars[tag_id] = var

        ctk.CTkLabel(
            fields_panel,
            text="Only common top-level EXIF fields are shown.\nGPS and maker-note data are left untouched.",
            text_color=MUTED, justify="left", anchor="w"
        ).grid(row=len(EXIF_FIELDS), column=0, columnspan=2, padx=14, pady=(10, 10), sticky="w")

        side_panel = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10, width=220)
        side_panel.grid(row=1, column=1, sticky="ns", padx=(6, 2), pady=2)
        side_panel.grid_propagate(False)

        ctk.CTkLabel(side_panel, text="Preview", text_color=MUTED).pack(pady=(14, 6))
        self.preview_label = ctk.CTkLabel(side_panel, text="No\nImage", width=180, height=180,
                                           fg_color=PANEL_2, corner_radius=8, text_color=MUTED)
        self.preview_label.pack(padx=14, pady=6)

        _make_btn(side_panel, "Strip All EXIF", self._strip_all, **_BTN_DANGER).pack(padx=14, pady=(20, 4), fill="x")
        _make_btn(side_panel, "Save Changes", self._save_changes, **_BTN_ACCENT).pack(padx=14, pady=4, fill="x")
        _make_btn(side_panel, "Reload / Discard", self._reload_current).pack(padx=14, pady=4, fill="x")

        self.side_panel = side_panel
        self.fields_panel = fields_panel

        self.status_label = ctk.CTkLabel(self, text="", text_color=MUTED, anchor="w")
        self.status_label.grid(row=2, column=0, columnspan=2, sticky="ew", padx=4, pady=(6, 2))

        self._set_controls_enabled(False)

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
        path = filedialog.askopenfilename(
            title="Select image file",
            filetypes=[("Images", " ".join(f"*{e}" for e in IMAGE_EXTS)), ("All files", "*.*")])
        if path:
            self._load_file(path)

    def _load_file(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext not in IMAGE_EXTS:
            self._set_status(f"Unsupported file type: {ext}", error=True)
            return
        try:
            self.current_path = path
            self.path_label.configure(text=os.path.basename(path))
            self._populate_fields()
            self._populate_preview()
            self._set_controls_enabled(True)
            self._set_status("Loaded successfully.")
        except Exception as e:
            self._set_status(f"Failed to load file: {e}", error=True)
            messagebox.showerror("Metadata Editor", f"Could not load file:\n{e}")

    def _reload_current(self):
        if self.current_path:
            self._load_file(self.current_path)

    def _populate_fields(self):
        for var in self.field_vars.values():
            var.set("")
        try:
            with Image.open(self.current_path) as img:
                exif = img.getexif()
                for tag_id, _label in EXIF_FIELDS:
                    value = exif.get(tag_id)
                    if value:
                        self.field_vars[tag_id].set(str(value))
        except Exception as e:
            self._set_status(f"Could not read EXIF: {e}", error=True)

    def _populate_preview(self):
        try:
            img = Image.open(self.current_path)
            img.thumbnail((180, 180))
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            self._preview_ctk_image = ctk_img
            self.preview_label.configure(image=ctk_img, text="")
        except Exception:
            self.preview_label.configure(image=None, text="Preview\nunavailable")

    def _save_changes(self):
        if not self.current_path:
            return
        try:
            img = Image.open(self.current_path)
            exif = img.getexif()
            for tag_id, var in self.field_vars.items():
                value = var.get().strip()
                if value:
                    exif[tag_id] = value
                elif tag_id in exif:
                    del exif[tag_id]

            img.save(self.current_path, exif=exif.tobytes())
            self._set_status("Saved successfully.")
        except Exception as e:
            self._set_status(f"Save failed: {e}", error=True)
            messagebox.showerror("Metadata Editor", f"Could not save changes:\n{e}")

    def _strip_all(self):
        if not self.current_path:
            return
        try:
            img = Image.open(self.current_path)
            img.save(self.current_path, exif=b"")
            for var in self.field_vars.values():
                var.set("")
            self._set_status("EXIF data stripped.")
        except Exception as e:
            self._set_status(f"Strip failed: {e}", error=True)
            messagebox.showerror("Metadata Editor", f"Could not strip EXIF:\n{e}")
